"""Authentication and Role-Based Access Control tests."""
import pytest
from conftest import valid_payload
from triage import auth, db


def test_demo_accounts_seeded_and_passwords_hashed(client, db_path):
    student = db.get_user(db_path, "STU2026001")
    examiner = db.get_user(db_path, "EXM2026001")
    assert student is not None
    assert examiner is not None
    assert student["role"] == "student"
    assert examiner["role"] == "examiner"
    # Never stored plain-text
    assert student["password_hash"] != "Student@123"
    assert examiner["password_hash"] != "Examiner@123"
    assert student["password_hash"].startswith("$2b$") or student["password_hash"].startswith("$2a$")
    assert examiner["password_hash"].startswith("$2b$") or examiner["password_hash"].startswith("$2a$")
    assert auth.verify_password("Student@123", student["password_hash"])
    assert auth.verify_password("Examiner@123", examiner["password_hash"])


def test_student_and_examiner_login_flow(client):
    # Valid student login
    res_stu = client.post("/v1/auth/student/login", json={"user_id": "STU2026001", "password": "Student@123"})
    assert res_stu.status_code == 200
    stu_data = res_stu.json()
    assert "access_token" in stu_data
    assert stu_data["user"]["role"] == "student"
    assert stu_data["user"]["user_id"] == "STU2026001"
    stu_token = stu_data["access_token"]

    # Student /v1/auth/me
    me_stu = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {stu_token}"})
    assert me_stu.status_code == 200
    assert me_stu.json()["user_id"] == "STU2026001"
    assert me_stu.json()["role"] == "student"

    # Valid examiner login
    res_exm = client.post("/v1/auth/examiner/login", json={"user_id": "EXM2026001", "password": "Examiner@123"})
    assert res_exm.status_code == 200
    exm_data = res_exm.json()
    assert "access_token" in exm_data
    assert exm_data["user"]["role"] == "examiner"
    assert exm_data["user"]["user_id"] == "EXM2026001"
    exm_token = exm_data["access_token"]

    # Examiner /v1/auth/me
    me_exm = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {exm_token}"})
    assert me_exm.status_code == 200
    assert me_exm.json()["user_id"] == "EXM2026001"
    assert me_exm.json()["role"] == "examiner"


def test_login_invalid_credentials_rejected(client):
    # Wrong password
    r1 = client.post("/v1/auth/student/login", json={"user_id": "STU2026001", "password": "WrongPassword!"})
    assert r1.status_code == 401

    # Nonexistent user
    r2 = client.post("/v1/auth/student/login", json={"user_id": "NONEXISTENT", "password": "Password@123"})
    assert r2.status_code == 401


def test_cross_portal_login_rejected(client):
    # Student cannot log in to examiner portal
    r1 = client.post("/v1/auth/examiner/login", json={"user_id": "STU2026001", "password": "Student@123"})
    assert r1.status_code == 401

    # Examiner cannot log in to student portal
    r2 = client.post("/v1/auth/student/login", json={"user_id": "EXM2026001", "password": "Examiner@123"})
    assert r2.status_code == 401


def test_student_cannot_record_examiner_decision(client, run_worker):
    # Submit petition
    acc = client.post("/v1/petitions", json=valid_payload(student_ref="STU2026001")).json()
    rid = acc["run_id"]
    run_worker()

    # Log in as student
    stu_res = client.post("/v1/auth/student/login", json={"user_id": "STU2026001", "password": "Student@123"}).json()
    stu_token = stu_res["access_token"]

    # Attempt to post examiner decision with student token -> 403 Forbidden
    dec_res = client.post(
        f"/v1/runs/{rid}/examiner-decision",
        json={"decision": "accept-petition", "note": "Self-approving my petition.", "examiner_label": "Hacker"},
        headers={"Authorization": f"Bearer {stu_token}"},
    )
    assert dec_res.status_code == 403
    assert "role 'student' is not authorized" in dec_res.json()["detail"]


def test_examiner_records_decision_and_attributed(client, run_worker):
    acc = client.post("/v1/petitions", json=valid_payload(student_ref="STU2026001")).json()
    rid = acc["run_id"]
    run_worker()

    # Log in as examiner
    exm_res = client.post("/v1/auth/examiner/login", json={"user_id": "EXM2026001", "password": "Examiner@123"}).json()
    exm_token = exm_res["access_token"]

    # Post examiner decision
    dec_res = client.post(
        f"/v1/runs/{rid}/examiner-decision",
        json={"decision": "accept-petition", "note": "Verified genuine medical emergency.", "examiner_label": "Ignored"},
        headers={"Authorization": f"Bearer {exm_token}"},
    )
    assert dec_res.status_code == 201

    # Check that decision is attributed to Dr. Eleanor Vance
    run_view = client.get(f"/v1/runs/{rid}", headers={"Authorization": f"Bearer {exm_token}"}).json()
    decisions = run_view["examiner_decisions"]
    assert len(decisions) == 1
    assert decisions[0]["examiner_label"] == "Dr. Eleanor Vance"
    assert decisions[0]["decision"] == "accept-petition"


def test_student_data_isolation(client, run_worker):
    # Create petition for STU2026001
    acc1 = client.post("/v1/petitions", json=valid_payload(student_ref="STU2026001")).json()
    # Create petition for another synthetic student
    acc2 = client.post("/v1/petitions", json=valid_payload(student_ref="SYN-999999")).json()
    run_worker()

    # Student token
    stu_token = client.post("/v1/auth/student/login", json={"user_id": "STU2026001", "password": "Student@123"}).json()["access_token"]

    # Can access own petition
    r_own = client.get(f"/v1/runs/{acc1['run_id']}", headers={"Authorization": f"Bearer {stu_token}"})
    assert r_own.status_code == 200

    # CANNOT access another student's petition -> 403 Forbidden
    r_other = client.get(f"/v1/runs/{acc2['run_id']}", headers={"Authorization": f"Bearer {stu_token}"})
    assert r_other.status_code == 403

    # Listing runs as student automatically filters to only own petitions
    runs_res = client.get("/v1/runs", headers={"Authorization": f"Bearer {stu_token}"}).json()
    assert all(r["student_ref"] == "STU2026001" for r in runs_res["runs"])


def test_logout_revokes_session(client):
    login_res = client.post("/v1/auth/student/login", json={"user_id": "STU2026001", "password": "Student@123"}).json()
    token = login_res["access_token"]

    # Valid before logout
    assert client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200

    # Logout
    logout_res = client.post("/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert logout_res.status_code == 200

    # Invalid after logout
    assert client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_multi_student_profiles_and_demo_credentials_endpoint(client, db_path):
    # Verify all 3 synthetic students exist with full academic records
    for uid, expected_branch, expected_sem in [
        ("STU2026001", "Computer Science & Engineering", 6),
        ("STU2026002", "Information Science & Engineering", 4),
        ("STU2026003", "Electronics & Communication Engineering", 2),
    ]:
        u = db.get_user(db_path, uid)
        assert u is not None, f"Missing user {uid}"
        assert u["branch"] == expected_branch
        assert u["semester"] == expected_sem
        assert u["section"] in ("A", "B", "C")
        assert u["usn"].startswith("SYN-")

    # Verify demo credentials endpoint structure
    cred_res = client.get("/v1/auth/demo-credentials")
    assert cred_res.status_code == 200
    data = cred_res.json()
    assert "students" in data and len(data["students"]) == 3
    assert "examiners" in data and len(data["examiners"]) == 2
    # Verify backward compatible fields
    assert data["student"]["id"] == "STU2026001"
    assert data["examiner"]["id"] == "EXM2026001"


def test_seed_demo_petitions_workflow(client, db_path):
    # Call seeding function
    auth.seed_demo_petitions_if_needed(db_path)

    # Verify demo runs exist in database
    run1 = db.get_run(db_path, "run_demo_001")
    run2 = db.get_run(db_path, "run_demo_002")
    run3 = db.get_run(db_path, "run_demo_003")
    run4 = db.get_run(db_path, "run_demo_004")

    assert run1 is not None
    assert run2 is not None
    assert run3 is not None
    assert run4 is not None

    # Run 1: Accepted medical hospitalisation for STU2026001
    assert run1["petition"]["student_ref"] == "STU2026001"
    dec1 = db.list_examiner_decisions(db_path, "run_demo_001")
    assert len(dec1) >= 1
    assert dec1[0]["decision"] == "accept-petition"

    # Run 2: Rejected below 75% for STU2026001
    dec2 = db.list_examiner_decisions(db_path, "run_demo_002")
    assert dec2[0]["decision"] == "reject-petition"

    # Run 3: Awaiting decision for STU2026002 (pending in examiner queue)
    assert run3["petition"]["student_ref"] == "STU2026002"
    dec3 = db.list_examiner_decisions(db_path, "run_demo_003")
    assert len(dec3) == 0

    # Run 4: Request info for STU2026003
    assert run4["petition"]["student_ref"] == "STU2026003"
    dec4 = db.list_examiner_decisions(db_path, "run_demo_004")
    assert dec4[0]["decision"] == "request-more-information"

    # Idempotent: running again does not duplicate or error
    auth.seed_demo_petitions_if_needed(db_path)
    assert db.get_run(db_path, "run_demo_001") is not None


