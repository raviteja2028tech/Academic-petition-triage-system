"""Examiner view backend: human decision recorded separately from the AI recommendation, and supporting-document
upload validation. No authentication exists in this system, and these tests do not pretend otherwise."""
import io
import os

from conftest import valid_payload

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _finished_run(client, run_worker):
    rid = client.post("/v1/petitions", json=valid_payload()).json()["run_id"]
    run_worker()
    assert client.get(f"/v1/runs/{rid}").json()["status"] in ("completed", "escalated")
    return rid


def test_examiner_decision_is_stored_separately_from_ai_result(client, run_worker):
    rid = _finished_run(client, run_worker)
    before = client.get(f"/v1/runs/{rid}").json()
    r = client.post(f"/v1/runs/{rid}/examiner-decision",
                    json={"decision": "request-more-information", "note": "Need the original certificate.",
                          "examiner_label": "Examiner A"})
    assert r.status_code == 201 and "no authentication" in r.json()["note"].lower()
    after = client.get(f"/v1/runs/{rid}").json()
    assert after["result"] == before["result"] and after["status"] == before["status"]   # AI output untouched
    d = after["examiner_decisions"]
    assert len(d) == 1 and d[0]["decision"] == "request-more-information" and d[0]["examiner_label"] == "Examiner A"
    assert "route" in d[0]["ai_snapshot"]                       # the recommendation shown at decision time is frozen
    assert client.get("/v1/runs").json()["runs"][0]["examiner_decision"] == "request-more-information"


def test_examiner_decision_is_append_only(client, run_worker):
    rid = _finished_run(client, run_worker)
    for dec in ("request-more-information", "accept-petition"):
        assert client.post(f"/v1/runs/{rid}/examiner-decision",
                           json={"decision": dec, "note": "Reasoned note here.", "examiner_label": "EX"}).status_code == 201
    got = client.get(f"/v1/runs/{rid}").json()["examiner_decisions"]
    assert [x["decision"] for x in got] == ["request-more-information", "accept-petition"]


def test_examiner_decision_validation(client, run_worker):
    rid = _finished_run(client, run_worker)
    ok = {"decision": "reject-petition", "note": "Reasoned note here.", "examiner_label": "EX"}
    assert client.post(f"/v1/runs/{rid}/examiner-decision", json={**ok, "decision": "grant-under-provision"}).status_code == 422
    assert client.post(f"/v1/runs/{rid}/examiner-decision", json={**ok, "note": "short"}).status_code == 422
    assert client.post(f"/v1/runs/{rid}/examiner-decision", json={**ok, "extra": 1}).status_code == 422
    assert client.post("/v1/runs/run_nope/examiner-decision", json=ok).status_code == 404


def test_examiner_decision_refused_while_run_unfinished(client):
    rid = client.post("/v1/petitions", json=valid_payload()).json()["run_id"]   # queued, no worker started
    r = client.post(f"/v1/runs/{rid}/examiner-decision",
                    json={"decision": "reject-petition", "note": "Reasoned note here.", "examiner_label": "EX"})
    assert r.status_code == 409


def test_run_view_exposes_petition_for_examiner(client, run_worker):
    rid = _finished_run(client, run_worker)
    v = client.get(f"/v1/runs/{rid}").json()
    assert v["petition"]["student_ref"] == "SYN-000123" and v["examiner_decisions"] == [] and v["documents"] == []


def test_document_upload_accepts_pdf_and_png_and_serves_them_safely(client, run_worker):
    rid = _finished_run(client, run_worker)
    r = client.post(f"/v1/runs/{rid}/documents", files={"file": ("cert.pdf", io.BytesIO(PDF), "application/pdf")})
    assert r.status_code == 201 and r.json()["content_type"] == "application/pdf"
    assert "Not read" in r.json()["note"]
    r2 = client.post(f"/v1/runs/{rid}/documents", files={"file": ("scan.png", io.BytesIO(PNG), "image/png")})
    assert r2.status_code == 201
    docs = client.get(f"/v1/runs/{rid}").json()["documents"]
    assert [d["filename"] for d in docs] == ["cert.pdf", "scan.png"]
    dl = client.get(f"/v1/runs/{rid}/documents/{docs[0]['id']}")
    assert dl.status_code == 200 and dl.content == PDF
    assert dl.headers["x-content-type-options"] == "nosniff" and "attachment" in dl.headers["content-disposition"]


def test_document_upload_rejects_wrong_content_even_with_pdf_name_and_type(client, run_worker):
    rid = _finished_run(client, run_worker)
    r = client.post(f"/v1/runs/{rid}/documents", files={"file": ("evil.pdf", io.BytesIO(b"MZ\x90\x00 not a pdf"), "application/pdf")})
    assert r.status_code == 415
    r = client.post(f"/v1/runs/{rid}/documents", files={"file": ("a.pdf", io.BytesIO(b"<html><script>1</script>"), "application/pdf")})
    assert r.status_code == 415
    assert client.get(f"/v1/runs/{rid}").json()["documents"] == []


def test_document_upload_size_count_duplicate_and_unknown_run(client, run_worker):
    rid = _finished_run(client, run_worker)
    big = PDF + b"0" * (2 * 1024 * 1024)
    assert client.post(f"/v1/runs/{rid}/documents", files={"file": ("big.pdf", io.BytesIO(big), "application/pdf")}).status_code == 413
    assert client.post(f"/v1/runs/{rid}/documents", files={"file": ("a.pdf", io.BytesIO(PDF), "application/pdf")}).status_code == 201
    assert client.post(f"/v1/runs/{rid}/documents", files={"file": ("a2.pdf", io.BytesIO(PDF), "application/pdf")}).status_code == 409  # duplicate
    for i in range(2):
        assert client.post(f"/v1/runs/{rid}/documents", files={"file": (f"b{i}.pdf", io.BytesIO(PDF + bytes([i + 1])), "application/pdf")}).status_code == 201
    assert client.post(f"/v1/runs/{rid}/documents", files={"file": ("c.pdf", io.BytesIO(PDF + b"9"), "application/pdf")}).status_code == 409  # > 3
    assert client.post("/v1/runs/run_nope/documents", files={"file": ("a.pdf", io.BytesIO(PDF), "application/pdf")}).status_code == 404


def test_document_filename_is_sanitised_and_never_used_as_path(client, run_worker, db_path):
    rid = _finished_run(client, run_worker)
    r = client.post(f"/v1/runs/{rid}/documents", files={"file": ("../../etc/pass wd<script>.pdf", io.BytesIO(PDF), "application/pdf")})
    assert r.status_code == 201
    name = r.json()["filename"]
    assert "/" not in name and "<" not in name and ".." not in name.replace("...", "")
    folder = os.path.join(os.path.dirname(db_path), "uploads", rid)
    stored = os.listdir(folder)
    assert len(stored) == 1 and stored[0].endswith(".pdf") and "pass" not in stored[0]


def test_oversized_petition_body_is_rejected_without_storing_it(client, db_path):
    import json as _json
    big = _json.dumps({"petition_text": "x" * 70000})
    r = client.post("/v1/petitions", content=big, headers={"content-type": "application/json"})
    assert r.status_code == 413
    from triage import db
    assert db.count_quarantine(db_path) == 0 and db.count_runs(db_path) == 0                         # not stored anywhere


def test_decision_and_upload_endpoints_are_rate_limited(make_client, run_worker, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "3")
    c = make_client()
    rid = c.post("/v1/petitions", json=valid_payload(), headers={"x-client-id": "submitter"}).json()["run_id"]
    run_worker()
    body = {"decision": "request-more-information", "note": "Reasoned note here.", "examiner_label": "EX"}
    codes = [c.post(f"/v1/runs/{rid}/examiner-decision", json=body, headers={"x-client-id": "ex1"}).status_code for _ in range(5)]
    assert codes[:3] == [201, 201, 201] and codes[3:] == [429, 429]
    # a different client is unaffected, and the petition-submission counter is separate
    assert c.post(f"/v1/runs/{rid}/examiner-decision", json=body, headers={"x-client-id": "ex2"}).status_code == 201


def test_run_list_filters_and_summary_fields(client, run_worker):
    a = client.post("/v1/petitions", json=valid_payload(student_ref="SYN-000111")).json()["run_id"]
    b = client.post("/v1/petitions", json=valid_payload(student_ref="SYN-000222")).json()["run_id"]
    run_worker()
    got = client.get("/v1/runs", params={"student_ref": "SYN-000222"}).json()["runs"]
    assert [r["run_id"] for r in got] == [b] and got[0]["course_code"] == "CS101" and got[0]["attendance_percentage"] == 80.0
    assert client.get("/v1/runs", params={"status": "completed"}).json()["runs"]
    assert client.get("/v1/runs", params={"status": "failed"}).json()["runs"] == []
    assert len(client.get("/v1/runs", params={"limit": 1, "offset": 1}).json()["runs"]) == 1
    assert client.get("/v1/runs", params={"petition_type": "re-evaluation"}).json()["runs"] == []


def test_stats_have_type_day_model_breakdown_and_agent_stats(client, run_worker):
    client.post("/v1/petitions", json=valid_payload())
    run_worker()
    st = client.get("/v1/stats").json()
    assert st["by_type"] == {"attendance": 1} and sum(d["total"] for d in st["by_day"].values()) == 1
    assert client.get("/v1/stats", params={"real_only": True}).json()["runs_considered"] == 0   # placeholder run: no real model
    ag = client.get("/v1/stats/agents").json()
    assert "agents" in ag and ag["runs_considered"] == 1


def test_system_overview_reports_queue_and_llm_state(client):
    j = client.get("/v1/system").json()
    assert "queue" in j and j["llm"]["configured"] is False and "limits" in j and j["retrieval"]["chroma_reachable"] is False
    assert "api_key" not in str(j).lower() and "key" not in j["llm"]


def test_rate_limit_counts_invalid_requests_too(make_client, run_worker, monkeypatch):
    """Bursts of INVALID bodies must not bypass the limiter (it runs before body validation)."""
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "5")
    c = make_client()
    rid = c.post("/v1/petitions", json=valid_payload()).json()["run_id"]
    run_worker()
    codes = [c.post(f"/v1/runs/{rid}/examiner-decision", json={"decision": "nonsense"}, headers={"x-client-id": "burst"}).status_code for _ in range(8)]
    assert codes[:5] == [422] * 5 and codes[5:] == [429] * 3
    up = [c.post(f"/v1/runs/{rid}/documents", headers={"x-client-id": "burst2"}).status_code for _ in range(8)]
    assert up[:5] == [422] * 5 and up[5:] == [429] * 3


def test_identical_petitions_create_independent_runs_by_design(client):
    """The API treats every POST as a new petition (no server-side de-duplication). The UI guards accidental double submits;
    this test pins the documented behaviour (KNOWN_LIMITATIONS.md) so a change is deliberate."""
    a = client.post("/v1/petitions", json=valid_payload()).json()["run_id"]
    b = client.post("/v1/petitions", json=valid_payload()).json()["run_id"]
    assert a != b and len(client.get("/v1/runs").json()["runs"]) == 2


def test_server_side_filters_awaiting_decision_and_real_model_only(client, run_worker, db_path):
    """The dashboard must not miss older petitions that fall outside a client-side page (found in the browser review)."""
    import json as _json
    from triage import db
    a = client.post("/v1/petitions", json=valid_payload(student_ref="SYN-000010")).json()["run_id"]
    b = client.post("/v1/petitions", json=valid_payload(student_ref="SYN-000020")).json()["run_id"]
    run_worker()
    # placeholder runs have no model; mark one as answered by a real model and the other by a stub, via the stored result
    for rid, models in ((a, ["real-model"]), (b, ["stub-model"])):
        r = db.get_run(db_path, rid)
        res = {**r["result"], "llm_models": models}
        db.set_status(db_path, rid, r["status"], result=res)
    assert client.get("/v1/runs", params={"real_only": True}).json()["matched"] == 1
    got = client.get("/v1/runs", params={"real_only": True}).json()["runs"]
    assert [x["run_id"] for x in got] == [a]
    pending = client.get("/v1/runs", params={"awaiting_decision": True}).json()
    assert pending["matched"] == 2
    client.post(f"/v1/runs/{a}/examiner-decision", json={"decision": "accept-petition", "note": "Reasoned note here.", "examiner_label": "EX"})
    assert [x["run_id"] for x in client.get("/v1/runs", params={"awaiting_decision": True}).json()["runs"]] == [b]
    assert [x["run_id"] for x in client.get("/v1/runs", params={"awaiting_decision": False}).json()["runs"]] == [a]
    both = client.get("/v1/runs", params={"awaiting_decision": True, "real_only": True}).json()
    assert both["matched"] == 0 and both["runs"] == []
    page = client.get("/v1/runs", params={"limit": 1}).json()
    assert page["matched"] == 2 and len(page["runs"]) == 1                    # matched counts beyond the page
