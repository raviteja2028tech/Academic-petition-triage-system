"""Phase 5: feedback storage/statistics, token + cost accounting (reported vs estimated, priced vs unpriced)."""
import json

import pytest
from fastapi.testclient import TestClient
from rq import Queue

from conftest import valid_payload
from test_agents import (COND_QUOTE, FakeLLM, env, go, happy_script, retriever, events)  # noqa: F401
from triage import cost, db
from triage.api.main import create_app
from triage.config import Settings
from triage.llm.client import LLMResponse

ESC = {"required": True, "reason": "committee_discretion", "detail": "VC decides."}


@pytest.fixture
def api(env, conn):
    return TestClient(create_app(settings_factory=Settings, redis_factory=lambda s: conn,
                                 queue_factory=lambda s, c: Queue(s.queue_name, connection=c)))


def finished_run(go):
    run, _ = go(happy_script(esc=ESC))
    return run["run_id"]


def test_cost_unknown_without_pricing_and_never_reported_as_zero(go):
    run, _ = go(happy_script(esc=ESC))
    c = run["result"]["cost"]
    assert c["llm_calls"] == 6 and c["prompt_tokens"] == 600 and c["token_source"] == "reported"
    assert c["estimated_cost_usd"] is None and c["pricing"] == "unavailable" and "cost unknown" in c["note"]


def test_cost_computed_from_configured_prices(go, monkeypatch):
    monkeypatch.setenv("PRICE_PROMPT_PER_1K", "0.5")
    monkeypatch.setenv("PRICE_COMPLETION_PER_1K", "1.5")
    run, _ = go(happy_script(esc=ESC))
    c = run["result"]["cost"]
    assert c["pricing"] == "configured"
    assert c["estimated_cost_usd"] == pytest.approx((600 * 0.5 + 120 * 1.5) / 1000)      # 6 calls x (100 + 20) tokens
    per_call = [e["detail"]["cost_usd"] for e in events(run, "llm_call") if e["detail"]["ok"]]
    assert sum(per_call) == pytest.approx(c["estimated_cost_usd"]) and len(per_call) == 6


def test_missing_provider_usage_is_estimated_and_labelled(go):
    class NoUsage(FakeLLM):
        def complete(self, role, system, user, timeout):
            r = super().complete(role, system, user, timeout)
            return LLMResponse(text=r.text, prompt_tokens=None, completion_tokens=None, model="m")
    run, _ = go(None, llm=NoUsage(happy_script(esc=ESC)))
    c = run["result"]["cost"]
    assert c["token_source"] == "estimated" and c["prompt_tokens"] > 0 and "ESTIMATED" in c["note"]
    assert {e["detail"]["token_source"] for e in events(run, "llm_call") if e["detail"]["ok"]} == {"estimated"}


def test_summarize_with_no_calls():
    c = cost.summarize({}, Settings())
    assert c["llm_calls"] == 0 and c["token_source"] == "none" and c["estimated_cost_usd"] is None


def test_feedback_roundtrip_stats_and_validation(go, api):
    rid = finished_run(go)
    assert api.post(f"/v1/runs/{rid}/feedback", json={"rating": 5, "agrees_with_recommendation": True,
                                                       "comment": "clear"}, headers={"X-Client-Id": "u1"}).status_code == 200
    api.post(f"/v1/runs/{rid}/feedback", json={"rating": 2, "agrees_with_recommendation": False}, headers={"X-Client-Id": "u2"})
    api.post(f"/v1/runs/{rid}/feedback", json={"rating": 4}, headers={"X-Client-Id": "u1"})   # u1 updates, not duplicates
    st = api.get("/v1/feedback").json()["stats"]
    assert st["count"] == 2 and st["mean_rating"] == 3.0 and st["satisfaction_rate"] == 0.5
    assert st["distribution"]["4"] == 1 and st["distribution"]["2"] == 1 and st["agreement_rate"] == 0.0
    for bad in ({"rating": 0}, {"rating": 6}, {"rating": 3, "comment": "x" * 501}, {"rating": 3, "extra": 1}, {}):
        assert api.post(f"/v1/runs/{rid}/feedback", json=bad).status_code == 422
    assert api.post("/v1/runs/run_nope/feedback", json={"rating": 3}).status_code == 404


def test_feedback_rejected_for_unfinished_run(api, env):
    s = Settings()
    rid = db.create_run(s.db_path, valid_payload(), None, "c")
    assert api.post(f"/v1/runs/{rid}/feedback", json={"rating": 3}).status_code == 409


def test_stats_endpoint_aggregates_runs_cost_and_feedback(go, api, monkeypatch):
    monkeypatch.setenv("PRICE_PROMPT_PER_1K", "1")
    monkeypatch.setenv("PRICE_COMPLETION_PER_1K", "1")
    rid = finished_run(go)
    finished_run(go)
    api.post(f"/v1/runs/{rid}/feedback", json={"rating": 5})
    st = api.get("/v1/stats").json()
    assert st["by_status"]["escalated"] == 2 and st["escalation_reasons"] == {"committee_discretion": 2}
    assert st["cost"]["runs_with_known_cost"] == 2
    per_run = (600 + 120) / 1000
    assert st["cost"]["avg_usd_per_run"] == pytest.approx(per_run) and st["cost"]["usd_per_100_runs"] == pytest.approx(per_run * 100)
    assert st["feedback"]["count"] == 1 and st["latency_seconds"]["n"] == 2


def test_stats_with_unpriced_runs_reports_unknown_not_zero(go, api):
    finished_run(go)
    c = api.get("/v1/stats").json()["cost"]
    assert c["runs_with_unknown_cost"] == 1 and c["usd_per_100_runs"] is None


def test_blank_price_variables_from_compose_mean_unknown_not_a_crash(monkeypatch):
    """Regression (found only by the Docker run): docker compose passes unset optional vars as empty strings."""
    monkeypatch.setenv("PRICE_PROMPT_PER_1K", "")
    monkeypatch.setenv("PRICE_COMPLETION_PER_1K", "  ")
    s = Settings()
    assert s.price_prompt_per_1k is None and s.price_completion_per_1k is None
    assert cost.call_cost(100, 100, s) is None
