import json

import pytest
from rq import Queue

from conftest import valid_payload
from triage import db


def test_valid_petition_returns_202_and_run_id(client):
    r = client.post("/v1/petitions", json=valid_payload())
    assert r.status_code == 202
    body = r.json()
    assert body["run_id"].startswith("run_") and body["status"] == "queued"
    assert body["status_url"] == f"/v1/runs/{body['run_id']}"


def test_submission_does_not_process_inline(client, conn):
    r = client.post("/v1/petitions", json=valid_payload())
    assert client.get(r.json()["status_url"]).json()["status"] == "queued"
    assert Queue("petitions", connection=conn).count == 1


MALFORMED = {
    "missing_field": lambda p: p.pop("course_code"),
    "attendance_over_100": lambda p: p.update(attendance_percentage=140, classes_held=None, classes_attended=None),
    "attended_gt_held": lambda p: p.update(classes_attended=60, attendance_percentage=None),
    "pct_inconsistent": lambda p: p.update(attendance_percentage=95.0),
    "bad_enum": lambda p: p.update(petition_type="hostel-fee"),
    "real_looking_id": lambda p: p.update(student_ref="1VT21CS001"),
    "short_text": lambda p: p.update(petition_text="too short"),
    "dates_reversed": lambda p: p.update(period_start="2026-03-01", period_end="2026-02-01"),
    "extra_field": lambda p: p.update(is_admin=True),
}


@pytest.mark.parametrize("name", list(MALFORMED))
def test_malformed_422_quarantined_no_run_no_job(name, client, conn, db_path):
    p = valid_payload()
    MALFORMED[name](p)
    r = client.post("/v1/petitions", json=p)
    assert r.status_code == 422
    body = r.json()
    assert body["errors"] and all({"field", "rule", "message"} <= set(e) for e in body["errors"])
    q = db.list_quarantine(db_path)
    assert len(q) == 1 and q[0]["id"] == body["quarantine_id"]
    assert len(q[0]["payload_hash"]) == 64 and q[0]["ts"] and q[0]["errors"]
    assert db.count_runs(db_path) == 0
    assert Queue("petitions", connection=conn).count == 0


def test_invalid_json_quarantined(client, db_path):
    r = client.post("/v1/petitions", content=b"{not json", headers={"content-type": "application/json"})
    assert r.status_code == 422
    assert db.count_quarantine(db_path) == 1 and db.count_runs(db_path) == 0


def test_worker_processes_job_and_transitions_persisted(client, run_worker):
    run_id = client.post("/v1/petitions", json=valid_payload()).json()["run_id"]
    run_worker()
    r = client.get(f"/v1/runs/{run_id}").json()
    assert r["status"] == "completed"
    assert [e["event"] for e in r["events"]] == ["queued", "running", "completed"]
    res = r["result"]
    assert res["mode"] == "placeholder" and res["evidence_used"] is False
    assert res["route"] is None and res["position"] == "NO_DETERMINATION" and res["citations"] == []


def test_unknown_run_404(client):
    assert client.get("/v1/runs/run_nope").status_code == 404


def test_data_survives_api_restart(make_client, run_worker):
    c1 = make_client()
    run_id = c1.post("/v1/petitions", json=valid_payload()).json()["run_id"]
    run_worker()
    c2 = make_client()  # a brand new app instance over the same storage
    assert c2.get(f"/v1/runs/{run_id}").json()["status"] == "completed"
    assert c2.get("/v1/runs").json()["counts"] == {"completed": 1}


def test_failed_job_marks_run_failed(client, conn, monkeypatch, db_path):
    run_id = client.post("/v1/petitions", json=valid_payload()).json()["run_id"]
    import triage.worker.tasks as tasks
    monkeypatch.setattr(tasks.time, "sleep", lambda s: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setenv("PLACEHOLDER_DELAY_SECONDS", "1")
    with pytest.raises(RuntimeError):
        tasks.process_petition(run_id)
    r = db.get_run(db_path, run_id)
    assert r["status"] == "failed" and "boom" in r["error"]


def test_process_is_idempotent(client, db_path):
    run_id = client.post("/v1/petitions", json=valid_payload()).json()["run_id"]
    from triage.worker.tasks import process_petition
    process_petition(run_id)
    process_petition(run_id)
    assert [e["event"] for e in db.get_run(db_path, run_id)["events"]].count("running") == 1


def test_healthz_and_readyz(client):
    assert client.get("/healthz").json() == {"status": "alive", "checks": {}}
    r = client.get("/readyz")
    assert r.status_code == 200 and r.json()["checks"]["redis"] == "ok" and r.json()["checks"]["database"] == "ok"
    assert r.json()["checks"]["chroma"] == "not-configured"


def test_readyz_reports_redis_down(env, conn):
    from fastapi.testclient import TestClient
    from triage.api.main import create_app
    from triage.config import Settings

    class Dead:
        def ping(self):
            raise ConnectionError("down")
    app = create_app(settings_factory=Settings, redis_factory=lambda s: Dead())
    r = TestClient(app).get("/readyz")
    assert r.status_code == 503 and r.json()["checks"]["redis"].startswith("down")


def test_submit_when_queue_down_returns_503_and_no_job(env):
    from fastapi.testclient import TestClient
    from triage.api.main import create_app
    from triage.config import Settings

    class Dead:
        def ping(self):
            raise ConnectionError("down")
    app = create_app(settings_factory=Settings, redis_factory=lambda s: Dead())
    r = TestClient(app).post("/v1/petitions", json=valid_payload())
    assert r.status_code == 503
    assert db.count_runs(str(env / "t.sqlite3")) == 0


def test_openapi_docs_exposed(client):
    assert client.get("/docs").status_code == 200
    assert "/v1/petitions" in client.get("/openapi.json").json()["paths"]


def test_corpus_status_before_ingestion(client):
    c = client.get("/v1/corpus").json()
    assert c["ready"] is False and c["index_exists"] is False and c["last_attempt_status"] is None
    assert "not run" in c["message"] or "No source" in c["message"]
    assert c["difficult_case"]["status"] == "PARTIALLY_VERIFIED"
    assert c["difficult_case"]["verified_passages_indexed"] is False
