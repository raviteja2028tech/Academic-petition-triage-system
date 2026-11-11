"""Authentication, password security (bcrypt), role-based access control and session management."""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt

from . import db

# ---------------- Demonstration Accounts ----------------
# NOTE: These credentials are strictly for development, testing, and demonstration purposes.
# In production mode (ENV='production' or ENVIRONMENT='production'), demo seeding is disabled.

DEMO_STUDENTS = [
    {
        "id": "STU2026001",
        "password": "Student@123",
        "name": "Alex Mercer",
        "email": "alex.mercer@apex.univ.edu",
        "branch": "Computer Science & Engineering",
        "semester": 6,
        "section": "A",
        "usn": "SYN-202601",
    },
    {
        "id": "STU2026002",
        "password": "Student@123",
        "name": "Priya Sharma",
        "email": "priya.sharma@apex.univ.edu",
        "branch": "Information Science & Engineering",
        "semester": 4,
        "section": "B",
        "usn": "SYN-202602",
    },
    {
        "id": "STU2026003",
        "password": "Student@123",
        "name": "Marcus Chen",
        "email": "marcus.chen@apex.univ.edu",
        "branch": "Electronics & Communication Engineering",
        "semester": 2,
        "section": "C",
        "usn": "SYN-202603",
    },
]

DEMO_EXAMINERS = [
    {
        "id": "EXM2026001",
        "password": "Examiner@123",
        "name": "Dr. Eleanor Vance",
        "email": "eleanor.vance@apex.univ.edu",
        "title": "Chairperson, Academic Petitions & Examination Board",
    },
    {
        "id": "EXM2026002",
        "password": "Examiner@123",
        "name": "Prof. Rajesh Kulkarni",
        "email": "rajesh.kulkarni@apex.univ.edu",
        "title": "Member Secretary, Board of Examinations",
    },
]

# Backward compatibility aliases
DEMO_STUDENT_ID = DEMO_STUDENTS[0]["id"]
DEMO_STUDENT_PASSWORD = DEMO_STUDENTS[0]["password"]
DEMO_STUDENT_NAME = DEMO_STUDENTS[0]["name"]
DEMO_STUDENT_EMAIL = DEMO_STUDENTS[0]["email"]

DEMO_EXAMINER_ID = DEMO_EXAMINERS[0]["id"]
DEMO_EXAMINER_PASSWORD = DEMO_EXAMINERS[0]["password"]
DEMO_EXAMINER_NAME = DEMO_EXAMINERS[0]["name"]
DEMO_EXAMINER_EMAIL = DEMO_EXAMINERS[0]["email"]

# Cached bcrypt hashes for speed
_PASSWORD_HASH_CACHE: dict[str, str] = {}


def hash_password(password: str, rounds: int = 12) -> str:
    """Hash password using bcrypt with salt rounds."""
    salt = bcrypt.gensalt(rounds=rounds)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Verify password against bcrypt hash in constant time."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def is_production() -> bool:
    env = os.environ.get("ENV", os.environ.get("ENVIRONMENT", "development")).lower()
    return env in ("production", "prod")


def seed_demo_accounts(db_path: str, force: bool = False) -> dict[str, Any]:
    """
    Seed development demo accounts (Students & Examiners) and realistic demonstration cases.
    Never stores plain-text passwords. Disabled in production mode unless forced.
    """
    if is_production() and not force:
        return {"status": "skipped", "reason": "production mode"}

    # Seed demo students
    for stu in DEMO_STUDENTS:
        pwd = stu["password"]
        if pwd not in _PASSWORD_HASH_CACHE:
            _PASSWORD_HASH_CACHE[pwd] = hash_password(pwd)
        existing = db.get_user(db_path, stu["id"])
        if not existing or force:
            db.upsert_user(
                db_path=db_path,
                user_id=stu["id"],
                password_hash=_PASSWORD_HASH_CACHE[pwd],
                role="student",
                name=stu["name"],
                email=stu["email"],
                branch=stu["branch"],
                semester=stu["semester"],
                section=stu["section"],
                usn=stu["usn"],
                is_active=1,
            )

    # Seed demo examiners
    for exm in DEMO_EXAMINERS:
        pwd = exm["password"]
        if pwd not in _PASSWORD_HASH_CACHE:
            _PASSWORD_HASH_CACHE[pwd] = hash_password(pwd)
        existing = db.get_user(db_path, exm["id"])
        if not existing or force:
            db.upsert_user(
                db_path=db_path,
                user_id=exm["id"],
                password_hash=_PASSWORD_HASH_CACHE[pwd],
                role="examiner",
                name=exm["name"],
                email=exm["email"],
                is_active=1,
            )

    # Seed demo petition cases (only outside automated test runner, so unit test fixtures start with 0 runs)
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        seed_demo_petitions_if_needed(db_path)

    return {
        "status": "seeded",
        "students": [s["id"] for s in DEMO_STUDENTS],
        "examiners": [e["id"] for e in DEMO_EXAMINERS],
        "student": DEMO_STUDENT_ID,
        "examiner": DEMO_EXAMINER_ID,
    }


def seed_demo_petitions_if_needed(db_path: str) -> None:
    """
    Seed coherent demonstration petitions with realistic AI recommendations and examiner decisions.
    Idempotent: checks for existence so runs are never duplicated on restart.
    """
    import json
    if db.get_run(db_path, "run_demo_001"):
        return

    ts1 = "2026-11-01T09:30:00.000Z"
    ts2 = "2026-11-02T14:15:00.000Z"
    ts3 = "2026-11-03T11:00:00.000Z"
    ts4 = "2026-11-04T16:45:00.000Z"

    # Case 1: STU2026001 (Alex Mercer) - 80% attendance, medical hospitalisation -> Decided (Accepted)
    p1 = {
        "petition_type": "attendance",
        "student_ref": "STU2026001",
        "programme": "Computer Science & Engineering",
        "course_code": "CS101",
        "semester": 6,
        "classes_held": 100,
        "classes_attended": 80,
        "attendance_percentage": 80.0,
        "medical_grounds_claimed": True,
        "documents_submitted": ["Medical Certificate", "Hospital Admission Summary"],
        "statement": "I was admitted to the university hospital with acute viral pneumonia for two weeks. My attendance dropped from 94% to 80%. Supporting hospital admission records and discharge summary are attached.",
    }
    r1 = {
        "mode": "agents",
        "route": "refer-to-committee",
        "position": "Attendance 80.0% is within the condonable discretionary band (75%–85%). Formal medical certificate attached.",
        "basis": "Clause 25OB10.0(4) establishes the mandatory 85% attendance standard. Clause 25OB10.0(5) authorizes shortage condonation up to 10% by the Vice-Chancellor on medical grounds with verified documentary evidence.",
        "disclaimer": "This is an AI-assisted regulatory triage recommendation, not a final administrative decision. Final determination rests with the designated University Examination Authority.",
        "message": "Petition evaluated against VTU / University Academic Regulations.",
        "escalation": {
            "required": True,
            "reason": "committee_discretion",
            "detail": "Shortage between 75% and 85% with genuine medical evidence requires Vice-Chancellor condonation discretion."
        },
        "citations": [
            {
                "evidence_id": "CIT-01",
                "chunk_id": "chunk_25OB10_4",
                "document": "VTU-Regulations.pdf",
                "chapter": "25OB10.0 Attendance and Eligibility",
                "clause_id": "25OB10.0(4)",
                "page": 18,
                "quote": "Each semester shall be considered as a unit and the candidate has to put in a minimum attendance of 85% in each subject",
                "verified": True
            },
            {
                "evidence_id": "CIT-02",
                "chunk_id": "chunk_25OB10_5",
                "document": "VTU-Regulations.pdf",
                "chapter": "25OB10.0 Attendance and Eligibility",
                "clause_id": "25OB10.0(5)",
                "page": 19,
                "quote": "shortage of attendance up to 10% may be condoned by the Vice-Chancellor on valid grounds such as medical reasons, with documentary evidence",
                "verified": True
            }
        ],
        "open_questions": [
            {
                "id": "OQ-01",
                "topic": "10% condonation ceiling",
                "text": "Whether 10% condonation applies to classes held or percentage points below 85%."
            }
        ],
        "human_review_checklist": [
            "Verify genuine hospital admission discharge summary and physician registration number.",
            "Check that prior semester attendance met standard academic criteria.",
            "Confirm no simultaneous unauthorized absence in practical laboratory sessions."
        ],
        "llm_models": ["academic-triage-model"],
        "triage": {
            "confidence": 0.94,
            "summary": "Attendance shortage petition for CS101 on medical grounds (80.0%). Requires condonation discretion.",
            "flags": [],
            "classified_type": "attendance",
            "declared_type": "attendance",
            "attendance_percentage": 80.0,
            "medical_grounds_claimed": True,
            "documentation": "medical_certificate",
            "supported": True
        }
    }

    # Case 2: STU2026001 (Alex Mercer) - 71% attendance, below 75% floor -> Decided (Rejected)
    p2 = {
        "petition_type": "attendance",
        "student_ref": "STU2026001",
        "programme": "Computer Science & Engineering",
        "course_code": "MATH201",
        "semester": 6,
        "classes_held": 100,
        "classes_attended": 71,
        "attendance_percentage": 71.0,
        "medical_grounds_claimed": True,
        "documents_submitted": ["Clinic Receipt"],
        "statement": "I had high fever and missed classes. My current attendance is 71%. Requesting condonation.",
    }
    r2 = {
        "mode": "agents",
        "route": "reject",
        "position": "Attendance 71.0% is strictly below the minimum statutory condonation floor of 75.0%.",
        "basis": "Under clause 25OB10.0(4) and 25OB10.0(5), the maximum allowable condonation is 10%, meaning attendance below 75% cannot be condoned under any circumstance.",
        "disclaimer": "This is an AI-assisted regulatory triage recommendation, not a final administrative decision.",
        "message": "Petition evaluated against VTU / University Academic Regulations.",
        "escalation": {
            "required": True,
            "reason": "attendance_below_hard_floor",
            "detail": "71.0% is below the absolute statutory threshold (75.0%)."
        },
        "citations": [
            {
                "evidence_id": "CIT-03",
                "chunk_id": "chunk_25OB10_4",
                "document": "VTU-Regulations.pdf",
                "chapter": "25OB10.0 Attendance and Eligibility",
                "clause_id": "25OB10.0(4)",
                "page": 18,
                "quote": "Each semester shall be considered as a unit and the candidate has to put in a minimum attendance of 85% in each subject",
                "verified": True
            }
        ],
        "open_questions": [],
        "human_review_checklist": ["Confirm lack of statutory basis for attendance under 75%."],
        "llm_models": ["academic-triage-model"],
        "triage": {
            "confidence": 0.98,
            "summary": "Attendance 71.0% is below the statutory minimum floor.",
            "flags": ["below_hard_floor"],
            "classified_type": "attendance",
            "declared_type": "attendance",
            "attendance_percentage": 71.0,
            "medical_grounds_claimed": True,
            "documentation": "clinic_receipt",
            "supported": True
        }
    }

    # Case 3: STU2026002 (Priya Sharma) - 77.8% attendance, University Sports -> PENDING REVIEW
    p3 = {
        "petition_type": "attendance",
        "student_ref": "STU2026002",
        "programme": "Information Science & Engineering",
        "course_code": "IS301",
        "semester": 4,
        "classes_held": 90,
        "classes_attended": 70,
        "attendance_percentage": 77.8,
        "medical_grounds_claimed": False,
        "documents_submitted": ["Sports Board Letter", "Tournament Certificate"],
        "statement": "Represented the university at the All-India Inter-University Athletics Championship in New Delhi. Official duty leave certification from Directorate of Physical Education is attached.",
    }
    r3 = {
        "mode": "agents",
        "route": "refer-to-committee",
        "position": "Attendance 77.8% is within the condonable band. Official institutional representation claimed.",
        "basis": "Clause 25OB10.0(5) allows condonation up to 10% for valid reasons with documentary evidence. University sports representation with Directorate endorsement constitutes valid grounds.",
        "disclaimer": "This is an AI-assisted regulatory triage recommendation, not a final administrative decision.",
        "message": "Petition evaluated against VTU / University Academic Regulations.",
        "escalation": {
            "required": True,
            "reason": "committee_discretion",
            "detail": "Inter-university sports duty leave condonation requires examination board review."
        },
        "citations": [
            {
                "evidence_id": "CIT-04",
                "chunk_id": "chunk_25OB10_5",
                "document": "VTU-Regulations.pdf",
                "chapter": "25OB10.0 Attendance and Eligibility",
                "clause_id": "25OB10.0(5)",
                "page": 19,
                "quote": "shortage of attendance up to 10% may be condoned by the Vice-Chancellor on valid grounds such as medical reasons, with documentary evidence",
                "verified": True
            }
        ],
        "open_questions": [],
        "human_review_checklist": ["Verify Directorate of Physical Education duty leave deputation order."],
        "llm_models": ["academic-triage-model"],
        "triage": {
            "confidence": 0.91,
            "summary": "University sports representation duty leave petition (77.8%).",
            "flags": [],
            "classified_type": "attendance",
            "declared_type": "attendance",
            "attendance_percentage": 77.8,
            "medical_grounds_claimed": False,
            "documentation": "sports_certificate",
            "supported": True
        }
    }

    # Case 4: STU2026003 (Marcus Chen) - 81.25% attendance, Family Emergency -> Request Info
    p4 = {
        "petition_type": "attendance",
        "student_ref": "STU2026003",
        "programme": "Electronics & Communication Engineering",
        "course_code": "EC102",
        "semester": 2,
        "classes_held": 80,
        "classes_attended": 65,
        "attendance_percentage": 81.25,
        "medical_grounds_claimed": False,
        "documents_submitted": [],
        "statement": "Family bereavement and emergency travel. Attendance is 81.25%. Requesting academic condonation.",
    }
    r4 = {
        "mode": "agents",
        "route": "refer-to-committee",
        "position": "Attendance 81.25% is in the condonable band, but no documentary evidence was submitted.",
        "basis": "Clause 25OB10.0(5) requires 'documentary evidence' for any condonation consideration.",
        "disclaimer": "This is an AI-assisted regulatory triage recommendation, not a final administrative decision.",
        "message": "Petition evaluated against VTU / University Academic Regulations.",
        "escalation": {
            "required": True,
            "reason": "missing_documentation",
            "detail": "Statute requires documentary evidence for condonation."
        },
        "citations": [
            {
                "evidence_id": "CIT-05",
                "chunk_id": "chunk_25OB10_5",
                "document": "VTU-Regulations.pdf",
                "chapter": "25OB10.0 Attendance and Eligibility",
                "clause_id": "25OB10.0(5)",
                "page": 19,
                "quote": "with documentary evidence",
                "verified": True
            }
        ],
        "open_questions": [],
        "human_review_checklist": ["Request formal family emergency attestation or proof of travel."],
        "llm_models": ["academic-triage-model"],
        "triage": {
            "confidence": 0.88,
            "summary": "Attendance 81.25% with missing documentation.",
            "flags": ["no_documentation"],
            "classified_type": "attendance",
            "declared_type": "attendance",
            "attendance_percentage": 81.25,
            "medical_grounds_claimed": False,
            "documentation": "none",
            "supported": True
        }
    }

    try:
        with db.connect(db_path) as c:
            for run_id, ts, pet, res in [
                ("run_demo_001", ts1, p1, r1),
                ("run_demo_002", ts2, p2, r2),
                ("run_demo_003", ts3, p3, r3),
                ("run_demo_004", ts4, p4, r4),
            ]:
                c.execute(
                    "INSERT OR IGNORE INTO runs(run_id, status, created_at, updated_at, client_id, correlation_id, mode, petition_json, result_json) "
                    "VALUES(?, 'escalated', ?, ?, 'demo_client', 'corr_demo', 'agents', ?, ?)",
                    (run_id, ts, ts, json.dumps(pet), json.dumps(res))
                )
                c.execute(
                    "INSERT OR IGNORE INTO run_events(run_id, ts, event, detail_json) VALUES(?, ?, 'agent_end', ?)",
                    (run_id, ts, json.dumps({"agent": "verifier", "ok": True}))
                )

        # Record examiner decisions for decided cases
        db.add_examiner_decision(
            db_path=db_path,
            run_id="run_demo_001",
            examiner_label="Dr. Eleanor Vance (EXM2026001)",
            decision="accept-petition",
            note="Approved under regulation 25OB10.0(5) condonation after reviewing verified hospital admission documentation and attending physician endorsement.",
            ai_snapshot=r1,
        )
        db.add_examiner_decision(
            db_path=db_path,
            run_id="run_demo_002",
            examiner_label="Dr. Eleanor Vance (EXM2026001)",
            decision="reject-petition",
            note="Attendance of 71.0% is below the statutory 75.0% absolute floor prescribed under regulation 25OB10.0(4). The university bye-laws do not empower any authority to condone attendance below 75%.",
            ai_snapshot=r2,
        )
        db.add_examiner_decision(
            db_path=db_path,
            run_id="run_demo_004",
            examiner_label="Prof. Rajesh Kulkarni (EXM2026002)",
            decision="request-more-information",
            note="Discretionary condonation requires verifiable documentary proof under statute 25OB10.0(5). Please upload official attestation or formal certification within 5 working days.",
            ai_snapshot=r4,
        )
    except Exception:
        pass


def authenticate_user(
    db_path: str,
    user_id: str,
    password: str,
    expected_role: Optional[str] = None,
) -> Optional[dict]:
    """Verify credentials and return user object if valid, None otherwise."""
    # Ensure demo accounts exist if in dev mode
    if not is_production():
        seed_demo_accounts(db_path)

    user = db.get_user(db_path, user_id)
    if not user:
        return None
    if not user.get("is_active"):
        return None
    if expected_role and user.get("role") != expected_role:
        return None
    if not verify_password(password, user.get("password_hash", "")):
        return None

    # Return safe user dict without password hash
    return {
        "user_id": user["user_id"],
        "role": user["role"],
        "name": user["name"],
        "email": user.get("email"),
        "branch": user.get("branch"),
        "semester": user.get("semester"),
        "section": user.get("section"),
        "usn": user.get("usn"),
        "created_at": user.get("created_at"),
    }


def create_user_session(
    db_path: str,
    user: dict,
    ttl_seconds: int = 7200,
) -> dict:
    """Create a new authenticated session token and record it in the database."""
    token = "sat_" + secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat(timespec="milliseconds")
    db.create_auth_session(db_path, token, user["user_id"], user["role"], expires_at)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": ttl_seconds,
        "user": user,
    }


def authenticate_token(db_path: str, token: str) -> Optional[dict]:
    """Verify an active bearer token and return the associated user profile."""
    session = db.get_auth_session(db_path, token)
    if not session:
        return None
    return {
        "user_id": session["user_id"],
        "role": session["role"],
        "name": session["name"],
        "email": session["email"],
        "branch": session.get("branch"),
        "semester": session.get("semester"),
        "section": session.get("section"),
        "usn": session.get("usn"),
        "session_token": session["token"],
    }


def logout_session(db_path: str, token: str) -> bool:
    """Revoke an active session token."""
    return db.revoke_auth_session(db_path, token)

