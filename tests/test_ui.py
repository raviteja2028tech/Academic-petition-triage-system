"""The Streamlit client must reach FastAPI through the HTTP client only."""
import pytest
from streamlit.testing.v1 import AppTest

from api_client import ApiClient, ApiError
from pathlib import Path
from conftest import valid_payload
from test_agents import retriever  # noqa: F401  (module-scoped index fixture)

APP = str(Path(__file__).resolve().parent.parent / "ui" / "app.py")


STUDENT_PAGES = {"New petition", "Track petition"}


def nav(at, label):
    """Switch to the view that owns `label`, then click its sidebar navigation button and re-run."""
    view = "Student" if label in STUDENT_PAGES else "Examiner"
    if at.session_state["view"] != view:
        at.session_state["view"] = view
        at.run()
    next(b for b in at.sidebar.button if b.label == label).click().run()


def test_api_client_roundtrip_against_real_app(client, run_worker):
    api = ApiClient(client=client)  # TestClient is an httpx.Client talking to the FastAPI app
    acc = api.submit(valid_payload())
    run_worker()
    assert api.run(acc["run_id"])["status"] == "completed"
    assert api.runs()["counts"] == {"completed": 1}
    assert api.corpus()["ready"] is False
    assert api.ready()["checks"]["database"] == "ok"


def test_api_client_surfaces_422_with_field_errors(client):
    api = ApiClient(client=client)
    with pytest.raises(ApiError) as ei:
        api.submit(valid_payload(semester=99))
    assert ei.value.status == 422 and ei.value.body["errors"][0]["field"] == "semester"


def test_api_client_unreachable_raises_apierror():
    api = ApiClient("http://127.0.0.1:9")
    with pytest.raises(ApiError):
        api.runs()


@pytest.mark.parametrize("page", ["Dashboard", "Corpus & system"])
def test_streamlit_pages_render_with_api(client, page):
    at = AppTest.from_file(APP, default_timeout=20)
    at.session_state["_api"] = ApiClient(client=client)
    at.run()
    nav(at, "New petition" if page == "Submit petition" else page)
    assert not at.exception
    assert not any("Backend unavailable" in m.value for m in at.markdown)


def test_streamlit_shows_error_state_when_api_down():
    at = AppTest.from_file(APP, default_timeout=20)
    at.session_state["_api"] = ApiClient("http://127.0.0.1:9")
    at.run()
    nav(at, "Dashboard")                                   # the Student landing page makes no API call; the dashboard does
    assert not at.exception
    assert any("Backend unavailable" in m.value for m in at.markdown)


def test_streamlit_submit_flow(client):
    at = AppTest.from_file(APP, default_timeout=20)
    at.session_state["_api"] = ApiClient(client=client)
    at.run()
    nav(at, "New petition")
    next(b for b in at.get("button") if b.label == "Submit petition").click().run()
    assert not at.exception
    assert any("Petition accepted" in m.value and "run_" in m.value for m in at.markdown)


def test_streamlit_renders_agent_result_with_citations_and_escalation():
    class Stub:
        def run(self, rid):
            return {"run_id": rid, "status": "escalated", "petition_type": "attendance", "student_ref": "SYN-000123",
                    "events": [{"ts": "2026-01-01T00:00:00.000+00:00", "event": "escalated", "detail": {}}],
                    "result": {"mode": "agents", "route": "refer-to-committee", "position": "Below the minimum.",
                               "basis": "See E1.", "disclaimer": "Recommendation only.",
                               "escalation": {"required": True, "reason": "committee_discretion", "detail": "VC decides."},
                               "citations": [{"clause_id": "25OB10.0(5)", "chapter": "25OB10.0 Attendance Requirement",
                                              "page": 19, "document": "doc.pdf", "quote": "may be condoned", "verified": True}],
                               "prompt_versions": {"triage": "triage_v1"}, "agent_stats": {"tool_calls": 3, "verify_attempts": 1}}}
        def ready(self):
            return {"checks": {"llm": "configured"}}

        def corpus(self):
            return {"ready": True}

        def trace(self, rid):
            return {"total_seconds": 1.2, "event_count": 1, "retry_count": 0, "correlation_id": "c", "agents": {},
                    "llm_calls": [], "retrieval_history": [], "retries_and_fallbacks": []}
    at = AppTest.from_file(APP, default_timeout=20)
    at.session_state["_api"] = Stub()
    at.session_state["run_id"] = "run_x"
    at.run()
    nav(at, "Run status")
    assert not at.exception
    html = " ".join(m.value for m in at.markdown)
    assert "committee_discretion" in html and "25OB10.0(5)" in html and "No final decision" in html


# ---- UI + API together (the UI talks to the real FastAPI app through the HTTP client interface)
def _agent_client(client, monkeypatch, retriever_fixture):
    from test_agents import FakeLLM, happy_script
    from triage.agents import runtime
    monkeypatch.setenv("AGENT_MODE", "agents")
    monkeypatch.setattr(runtime, "make_llm", lambda st: FakeLLM(happy_script(esc={"required": True, "reason": "committee_discretion", "detail": "VC decides."})))
    monkeypatch.setattr(runtime, "make_retriever", lambda st: retriever_fixture)


def test_ui_and_api_together_run_page_shows_trace_retrieval_feedback(client, run_worker, monkeypatch, retriever):
    ret = retriever
    _agent_client(client, monkeypatch, ret)
    api = ApiClient(client=client)
    rid = api.submit(valid_payload())["run_id"]
    run_worker()
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["_api"] = api
    at.session_state["run_id"] = rid
    at.run()
    nav(at, "Run status")
    assert not at.exception
    html = " ".join(m.value for m in at.markdown)
    assert "25OB10.0(5)" in html and "step done" in html and "search_keyword" in html       # citations, stepper, retrieval history
    assert len(at.tabs) == 4
    next(b for b in at.get("button") if b.label == "Send feedback").click().run()        # feedback form submit
    assert any("Feedback stored" in m.value for m in at.markdown)
    assert api.feedback()["stats"]["count"] == 1


def test_evaluation_and_health_pages_render_from_the_api(client, tmp_path, monkeypatch):
    monkeypatch.setenv("EVAL_RESULTS_DIR", str(Path(APP).parent.parent / "eval" / "results"))
    for page in ("Evaluation", "Health & feedback"):
        at = AppTest.from_file(APP, default_timeout=30)
        at.session_state["_api"] = ApiClient(client=client)
        at.run()
        nav(at, "New petition" if page == "Submit petition" else page)
        assert not at.exception, page
        assert not any("Backend unavailable" in m.value for m in at.markdown)
    html = " ".join(m.value for m in at.markdown)
    assert "Dependency status" in html or "Workers" in html


def test_ui_warns_when_the_result_came_from_a_stub_model():
    class Stub:
        def run(self, rid):
            return {"run_id": rid, "status": "escalated", "petition_type": "attendance", "student_ref": "SYN-000123", "events": [],
                    "result": {"mode": "agents", "route": "refer-to-committee", "position": "p", "basis": "b", "disclaimer": "d",
                               "llm_models": ["stub-model"], "escalation": {"required": True, "reason": "committee_discretion", "detail": "x"},
                               "citations": []}}

        def ready(self):
            return {"checks": {}}

        def corpus(self):
            return {"ready": True}

        def trace(self, rid):
            return {"total_seconds": 0, "event_count": 0, "retry_count": 0, "agents": {}, "llm_calls": [], "retrieval_history": [], "retries_and_fallbacks": []}
    at = AppTest.from_file(APP, default_timeout=20)
    at.session_state["_api"] = Stub()
    at.session_state["run_id"] = "run_x"
    at.run()
    nav(at, "Run status")
    assert any("not real AI reasoning" in m.value for m in at.markdown)


def test_student_view_is_default_and_has_no_examiner_pages():
    at = AppTest.from_file(APP, default_timeout=20)
    at.session_state["_api"] = ApiClient("http://127.0.0.1:9")
    at.run()
    labels = [b.label for b in at.sidebar.button]
    assert "New petition" in labels and "Track petition" in labels and "Review petition" not in labels
    assert any("not a login" in c.value.lower() for c in at.sidebar.caption)           # honest about the missing authentication


def test_track_petition_shows_human_review_required_and_no_decision_yet(client, run_worker, monkeypatch, retriever):
    _agent_client(client, monkeypatch, retriever)
    api = ApiClient(client=client)
    rid = api.submit(valid_payload())["run_id"]
    run_worker()
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["_api"] = api
    at.session_state["run_id"] = rid
    at.run()
    nav(at, "Track petition")
    assert not at.exception
    html = " ".join(m.value for m in at.markdown)
    assert "Human review is required" in html and "25OB10.0(5)" in html and "No human decision recorded yet" in html


def test_examiner_review_records_a_separate_human_decision(client, run_worker, monkeypatch, retriever):
    _agent_client(client, monkeypatch, retriever)
    api = ApiClient(client=client)
    rid = api.submit(valid_payload())["run_id"]
    run_worker()
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["_api"] = api
    at.session_state["run_id"] = rid
    at.run()
    nav(at, "Review petition")
    assert not at.exception
    html = " ".join(m.value for m in at.markdown)
    assert "Petition as submitted" in html and "separate from the AI recommendation" in html and "SYN-000123" in html
    # submitting without choosing a decision is refused (no default decision)
    next(b for b in at.get("button") if b.label == "Record my decision").click().run()
    assert any("Choose a decision" in m.value for m in at.markdown)
    assert api.run(rid)["examiner_decisions"] == []
    labels = [t for t in at.text_input if "self-declared" in t.label]
    labels[0].input("Examiner A")
    next(r for r in at.radio if "Your decision" in r.label).set_value("request-more-information")
    next(t for t in at.text_area if "reasoning" in t.label).input("Certificate dates are unclear; please resubmit.")
    at.run()
    next(b for b in at.get("button") if b.label == "Record my decision").click().run()
    stored = api.run(rid)
    assert stored["examiner_decisions"][0]["decision"] == "request-more-information"
    assert stored["status"] == "escalated" and stored["result"]["route"] == "refer-to-committee"   # AI output unchanged


def test_dashboard_review_button_opens_that_run_in_the_review_page(client, run_worker, monkeypatch, retriever):
    _agent_client(client, monkeypatch, retriever)
    api = ApiClient(client=client)
    rid = api.submit(valid_payload())["run_id"]
    run_worker()
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["_api"] = api
    at.run()
    nav(at, "Dashboard")
    next(b for b in at.get("button") if b.label == "Review").click().run()          # regression: Run ID box stayed empty
    assert not at.exception
    assert any(t.value == rid for t in at.text_input if t.label == "Run ID")
    assert "Petition as submitted" in " ".join(m.value for m in at.markdown)
