import fakeredis
import pytest
from fastapi.testclient import TestClient
from rq import Queue, SimpleWorker

from triage import db
from triage.api.main import create_app
from triage.config import Settings


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.sqlite3"))
    monkeypatch.setenv("PLACEHOLDER_DELAY_SECONDS", "0")
    monkeypatch.setenv("AGENT_MODE", "placeholder")   # Phase 1 plumbing tests; agent tests live in test_agents.py
    monkeypatch.setenv("CHROMA_HOST", "")
    monkeypatch.setenv("CORPUS_DIR", str(tmp_path / "corpus"))
    return tmp_path


@pytest.fixture(autouse=True)
def _isolated_metrics(monkeypatch):
    """Never touch a real Redis from unit tests: metrics and reliability state go to an in-memory fake."""
    from triage.reliability import deps, metrics
    deps.reset_redis_state()          # the "Redis recently down" window is process-global: never leak it between tests
    fake = fakeredis.FakeStrictRedis()
    monkeypatch.setattr(deps, "redis_for", lambda s: fake)
    metrics.set_metrics(metrics.Metrics(fake))
    yield fake
    metrics.set_metrics(None)
    deps.reset_redis_state()


@pytest.fixture
def conn(_isolated_metrics):
    """The same in-memory Redis the metrics / reliability code uses, as production shares one Redis."""
    return _isolated_metrics


@pytest.fixture
def make_client(env, conn):
    def _make():
        app = create_app(settings_factory=Settings,
                         redis_factory=lambda s: conn,
                         queue_factory=lambda s, c: Queue(s.queue_name, connection=c))
        return TestClient(app)
    return _make


@pytest.fixture
def client(make_client):
    return make_client()


@pytest.fixture
def run_worker(conn):
    def _run():
        q = Queue("petitions", connection=conn)
        SimpleWorker([q], connection=conn).work(burst=True)
    return _run


@pytest.fixture
def db_path(env):
    return str(env / "t.sqlite3")


def valid_payload(**over):
    p = {
        "student_ref": "SYN-000123", "program": "Computer Science", "admission_batch": "2025-26",
        "petition_type": "attendance", "course_code": "CS101", "semester": 3,
        "classes_held": 50, "classes_attended": 40, "attendance_percentage": 80.0,
        "reason_category": "medical", "medical_documentation": "certificate",
        "period_start": "2026-01-05", "period_end": "2026-02-10",
        "petition_text": "I was hospitalised for three weeks and request consideration of my attendance shortage.",
    }
    p.update(over)
    return p
