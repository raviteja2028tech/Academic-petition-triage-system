"""Phase 6 tests: JSON logs + redaction, correlation ids through the queue, tracing context propagation, run-trace
reconstruction, readiness/metrics endpoints. OpenTelemetry uses an in-memory exporter (no Jaeger needed)."""
import io
import json
import logging

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from rq import Queue, SimpleWorker

from conftest import valid_payload
from test_agents import (COND_QUOTE, FakeLLM, act, env, go, happy_script, retriever, events)  # noqa: F401
from triage import db
from triage.agents import runtime
from triage.api.main import create_app
from triage.config import Settings
from triage.observability import (configure_logging, current_traceparent, redact, set_context, setup_tracing, span)
from triage.observability import tracing
from triage.observability.trace import build_trace

ESC = {"required": True, "reason": "committee_discretion", "detail": "VC decides."}


@pytest.fixture
def logbuf():
    buf = io.StringIO()
    configure_logging("test", "DEBUG", stream=buf)
    yield buf
    logging.getLogger().handlers.clear()


def lines(buf):
    return [json.loads(x) for x in buf.getvalue().splitlines() if x.strip()]


def test_logs_are_json_with_context_and_never_contain_secrets_or_petition_text(logbuf, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "supersecretkey-123456")
    set_context(correlation_id="corr-1", run_id="run_x")
    log = logging.getLogger("triage.test")
    log.info("calling with Authorization: Bearer abcdef1234567890 and key supersecretkey-123456 sk-ABCDEFGH12345678")
    log.info("event", extra={"petition_text": "my private medical story", "tool": "get_clause", "api_key": "x" * 10})
    try:
        raise ValueError("boom")
    except ValueError:
        log.exception("failed")
    out = logbuf.getvalue()
    assert "supersecretkey" not in out and "abcdef1234567890" not in out and "sk-ABCDEFGH" not in out
    assert "my private medical story" not in out
    recs = lines(logbuf)
    assert all(r["service"] == "test" and r["correlation_id"] == "corr-1" and r["run_id"] == "run_x" for r in recs)
    assert recs[1]["tool"] == "get_clause" and "petition_text" not in recs[1]
    assert recs[2]["exception"].startswith("ValueError") and "Traceback" not in out


def test_redact_helper():
    assert "[REDACTED]" in redact('{"api_key": "abcd1234efgh"}') and "Bearer [REDACTED]" in redact("Bearer abcdefghijkl")


@pytest.fixture
def exporter():
    exp = InMemorySpanExporter()
    assert setup_tracing("triage-test", exporter=exp, simple=True)
    yield exp
    tracing.shutdown_tracing()


def test_spans_nest_propagate_across_the_queue_and_exclude_sensitive_attributes(exporter):
    with span("api", petition_text="private story", api_key="k", safe="ok") as sp:
        tp = current_traceparent()
    assert tp and tp.startswith("00-")
    with tracing.use_parent(tp), span("worker.job"):
        with span("agent.research"):
            pass
    spans = {s.name: s for s in exporter.get_finished_spans()}
    assert spans["worker.job"].context.trace_id == spans["api"].context.trace_id            # one trace across processes
    assert spans["worker.job"].parent.span_id == spans["api"].context.span_id
    assert spans["agent.research"].parent.span_id == spans["worker.job"].context.span_id
    attrs = dict(spans["api"].attributes)
    assert attrs == {"safe": "ok"}


def test_pipeline_emits_agent_llm_and_tool_spans_without_petition_text(go, exporter):
    run, _ = go(happy_script(esc=ESC))
    names = [s.name for s in exporter.get_finished_spans()]
    assert {"agent.triage", "agent.research", "agent.verifier"} <= set(names)
    assert names.count("llm.call") == 6 and "tool.search_keyword" in names
    blob = json.dumps([dict(s.attributes) for s in exporter.get_finished_spans()], default=str)
    assert "hospitalised" not in blob and "petition_text" not in blob


@pytest.fixture
def api(env, conn):
    return TestClient(create_app(settings_factory=Settings, redis_factory=lambda s: conn,
                                 queue_factory=lambda s, c: Queue(s.queue_name, connection=c)))


def test_correlation_id_flows_from_request_to_run_events_worker_logs_and_response(api, conn, logbuf, monkeypatch, retriever):  # noqa: F811
    monkeypatch.setenv("AGENT_MODE", "agents")
    fake = FakeLLM(happy_script(esc=ESC))
    monkeypatch.setattr(runtime, "make_llm", lambda st: fake)
    monkeypatch.setattr(runtime, "make_retriever", lambda st: retriever)
    r = api.post("/v1/petitions", json=valid_payload(), headers={"X-Correlation-ID": "corr-abc-123"})
    assert r.status_code == 202 and r.headers["X-Correlation-ID"] == "corr-abc-123"
    rid = r.json()["run_id"]
    SimpleWorker([Queue("petitions", connection=conn)], connection=conn).work(burst=True)
    run = api.get(f"/v1/runs/{rid}").json()
    assert run["events"][0]["detail"]["correlation_id"] == "corr-abc-123"
    worker_logs = [x for x in lines(logbuf) if x["logger"] == "triage.worker"]
    assert worker_logs and all(x["correlation_id"] == "corr-abc-123" and x["run_id"] == rid for x in worker_logs)
    assert api.post("/v1/petitions", json=valid_payload()).headers["X-Correlation-ID"]          # generated when absent


def test_run_trace_endpoint_reconstructs_the_run_from_events(api, go):
    run, _ = go(happy_script(esc=ESC))
    t = api.get(f"/v1/runs/{run['run_id']}/trace").json()
    assert t["status"] == "escalated" and t["outcome"]["escalation"] == "committee_discretion" and t["outcome"]["citations"] == 2
    assert set(t["agents"]) == {"triage", "research", "verifier"}
    assert t["agents"]["research"]["tool_calls"] == 3 and t["agents"]["research"]["llm_calls"] == 4
    assert [h["tool"] for h in t["retrieval_history"]] == ["search_keyword", "search_keyword", "get_neighbouring_clauses"]
    assert any(r["clause_id"] == "25OB10.0(5)" for h in t["retrieval_history"] for r in h["results"])
    assert len(t["llm_calls"]) == 6 and t["timeline"][0]["event"] == "queued" and t["prompt_versions"]["research"] == "research_v1"
    assert api.get("/v1/runs/run_missing/trace").status_code == 404


def test_trace_shows_retries_and_failures(go):
    from test_reliability import ScriptedProvider, err, make_resilient
    from triage.reliability.resilient_llm import Provider
    r, _, _, _ = make_resilient([Provider("primary", ScriptedProvider([err("server", True)]))], attempts=3)
    run, _ = go(None, llm=r)
    t = build_trace(run)
    assert t["retry_count"] == 2 and t["agents"]["triage"]["failures"] == 1 and t["outcome"]["escalation"] == "llm_unavailable"


def test_readyz_reports_real_dependency_state(api, monkeypatch):
    for k in ("LLM_BASE_URL", "LLM_MODEL"):
        monkeypatch.delenv(k, raising=False)
    body = api.get("/readyz").json()
    c = body["checks"]
    assert body["status"] == "ready" and c["redis"] == "ok" and c["database"] == "ok"
    assert c["llm"] == "not-configured" and c["workers"] == "0" and "no_workers" in c["degraded"] and "llm_not_configured" in c["degraded"]
    monkeypatch.setenv("LLM_BASE_URL", "http://x/v1")
    monkeypatch.setenv("LLM_MODEL", "m")
    assert api.get("/readyz").json()["checks"]["llm"] == "configured"


def test_metrics_endpoint_is_valid_prometheus_text_with_gauges(api, conn):
    api.post("/v1/petitions", json=valid_payload())
    api.get("/healthz")
    text = api.get("/metrics").text
    assert "# TYPE http_requests_total counter" in text and 'http_requests_total{method="POST",route="/v1/petitions",status="202"} 1' in text
    assert "# TYPE http_request_seconds histogram" in text and 'http_request_seconds_bucket{le="+Inf",route="/v1/petitions"} 1' in text
    assert "queue_depth 1" in text and 'llm_breaker_state{provider="primary"} 0' in text and "workers_active 0" in text
    for line in text.splitlines():
        assert line.startswith("#") or len(line.rsplit(" ", 1)) == 2                      # name{labels} value


def test_unreachable_trace_collector_never_delays_a_job(monkeypatch):
    """Load-test finding: with tracing pointed at a dead collector each job waited in force_flush (~1.5-3 s)."""
    import time
    from triage.observability import tracing

    class Slow:
        calls = []

        def force_flush(self, timeout):
            Slow.calls.append(timeout)
            time.sleep(0.3)
            return False

    monkeypatch.setattr(tracing, "_provider", Slow())
    monkeypatch.setenv("WORKER_MODE", "simple")
    t0 = time.time(); tracing.flush_tracing()
    assert time.time() - t0 < 0.1 and Slow.calls == []                 # long-lived worker: no blocking flush at all
    monkeypatch.setenv("WORKER_MODE", "fork")                          # fork mode must flush, but backs off after a failure
    monkeypatch.setattr(tracing, "_flush_failures", 0)
    tracing.flush_tracing(); tracing.flush_tracing()
    assert Slow.calls == [3000, 300]
