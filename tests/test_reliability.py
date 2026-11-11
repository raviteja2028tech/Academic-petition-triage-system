"""Phase 4 tests: retries, breaker, resilient LLM, rate limiting, caches, degraded behaviour, worker failure.

Deterministic: fake clocks, recorded sleeps, seeded RNG, scripted providers, fakeredis. No network, no real LLM.
"""
import json
import random

import fakeredis
import httpx
import pytest

import time

from conftest import valid_payload
from test_agents import (FakeLLM, env, go, happy_script, retriever, events, triage_ok, DIFFICULT_RESEARCH)  # noqa: F401
from triage import db
from triage.agents import runtime
from triage.config import Settings
from triage.llm.client import CircuitOpen, LLMError, LLMResponse, OpenAICompatClient
from triage.reliability.breaker import CLOSED, HALF_OPEN, OPEN, CircuitBreaker
from triage.reliability.cache import (CachedEmbedder, CachedRetriever, corpus_fingerprint, invalidate_retrieval)
from triage.reliability.metrics import Metrics
from triage.reliability.ratelimit import check_rate
from triage.reliability.resilient_llm import Provider, ResilientLLM
from triage.reliability.retry import backoff_delay, call_with_retry
from triage.retrieval.embed import HashEmbedder


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def err(kind, retryable, retry_after=None):
    return LLMError(f"{kind} failure", kind, retryable, retry_after)


class ScriptedProvider:
    """Returns/raises items from a list in order (last repeats)."""

    def __init__(self, items):
        self.items, self.calls = items, 0

    def complete(self, role, system, user, timeout):
        it = self.items[min(self.calls, len(self.items) - 1)]
        self.calls += 1
        if isinstance(it, Exception):
            raise it
        return LLMResponse(text=it, model="m")


def make_resilient(providers, conn=None, clock=None, threshold=3, cooldown=30.0, attempts=3, sleeps=None):
    conn = conn or fakeredis.FakeStrictRedis()
    clock = clock or Clock()
    metrics = Metrics(conn)
    brs = {p.name: CircuitBreaker(conn, p.name, threshold, cooldown, clock=clock,
                                  on_transition=lambda n, o, nw: metrics.inc("llm_breaker_transitions_total", provider=n, to=nw))
           for p in providers}
    sl = sleeps if sleeps is not None else []
    r = ResilientLLM(providers, brs, metrics, attempts, 0.5, 8.0, sleep=sl.append, rng=random.Random(7))
    return r, brs, metrics, sl


def call(r):
    return r.complete("research", "sys", "usr", 5)


# ----------------------------------------------------------------- retry / backoff
def test_backoff_is_exponential_capped_and_jittered():
    rng = random.Random(1)
    for attempt, ceiling in [(1, 0.5), (2, 1.0), (3, 2.0), (4, 4.0), (5, 8.0), (9, 8.0)]:
        for _ in range(50):
            d = backoff_delay(attempt, 0.5, 8.0, rng)
            assert 0 <= d <= ceiling
    ds = {round(backoff_delay(3, 0.5, 8.0, rng), 6) for _ in range(20)}
    assert len(ds) > 10                                       # jitter: not a constant delay
    assert backoff_delay(1, 0.5, 8.0, rng, retry_after=3) >= 3          # Retry-After honoured
    assert backoff_delay(1, 0.5, 8.0, rng, retry_after=100) == 30.0     # but capped (RETRY_AFTER_CAP)


def test_retry_succeeds_after_transient_errors_and_records_sleeps():
    n, slept = {"c": 0}, []

    def fn():
        n["c"] += 1
        if n["c"] < 3:
            raise err("server", True)
        return "ok"
    assert call_with_retry(fn, max_attempts=3, base=0.5, cap=8, sleep=slept.append, rng=random.Random(2)) == "ok"
    assert n["c"] == 3 and len(slept) == 2


def test_non_retryable_error_is_never_retried():
    n = {"c": 0}

    def fn():
        n["c"] += 1
        raise err("auth", False)
    with pytest.raises(LLMError):
        call_with_retry(fn, max_attempts=5, base=0.1, cap=1, sleep=lambda d: None)
    assert n["c"] == 1


def test_retry_is_bounded_and_does_not_sleep_past_the_run_budget():
    n = {"c": 0}

    def fn():
        n["c"] += 1
        raise err("timeout", True)
    with pytest.raises(LLMError):
        call_with_retry(fn, max_attempts=3, base=0.1, cap=1, sleep=lambda d: None)
    assert n["c"] == 3
    n["c"] = 0
    with pytest.raises(LLMError):                              # no time left -> fail now instead of waiting
        call_with_retry(fn, max_attempts=5, base=1, cap=8, sleep=lambda d: None, remaining=lambda: 0.0)
    assert n["c"] == 1


# ----------------------------------------------------------------- circuit breaker
def test_breaker_full_cycle_closed_open_half_open_closed():
    conn, clk = fakeredis.FakeStrictRedis(), Clock()
    seen = []
    b = CircuitBreaker(conn, "x", failure_threshold=3, cooldown=30, clock=clk,
                       on_transition=lambda n, o, nw: seen.append((o, nw)))
    assert b.state == CLOSED and b.allow()
    b.record_failure(); b.record_failure()
    assert b.state == CLOSED and b.allow()
    b.record_failure()                                         # threshold reached
    assert b.state == OPEN and not b.allow()
    clk.t += 29
    assert not b.allow()                                       # still cooling down
    clk.t += 2
    assert b.state == HALF_OPEN
    assert b.allow() is True                                   # exactly one probe admitted
    assert b.allow() is False
    b.record_success()
    assert b.state == CLOSED and b.allow()
    assert seen == [(CLOSED, OPEN), (OPEN, HALF_OPEN), (HALF_OPEN, CLOSED)]


def test_breaker_failed_probe_reopens_and_success_resets_failure_count():
    conn, clk = fakeredis.FakeStrictRedis(), Clock()
    b = CircuitBreaker(conn, "y", 2, 10, clock=clk)
    b.record_failure(); b.record_success(); b.record_failure()
    assert b.state == CLOSED                                   # success reset the consecutive count
    b.record_failure()
    assert b.state == OPEN
    clk.t += 11
    assert b.allow()
    b.record_failure()                                         # probe failed
    assert b.state == OPEN and not b.allow()
    clk.t += 11
    assert b.state == HALF_OPEN


def test_breaker_state_is_shared_between_processes():
    conn, clk = fakeredis.FakeStrictRedis(), Clock()
    a, b = CircuitBreaker(conn, "z", 2, 30, clock=clk), CircuitBreaker(conn, "z", 2, 30, clock=clk)
    a.record_failure(); b.record_failure()
    assert a.state == OPEN and b.state == OPEN and not b.allow()


# ----------------------------------------------------------------- resilient LLM
def test_transient_failures_are_retried_then_succeed():
    p = ScriptedProvider([err("server", True), err("timeout", True), "answer"])
    r, brs, m, sleeps = make_resilient([Provider("primary", p)])
    assert call(r).text == "answer" and p.calls == 3 and len(sleeps) == 2
    snap = m.snapshot()
    assert snap['llm_retries_total{kind="server",provider="primary"}'] == 1
    assert snap['llm_calls_total{outcome="ok",provider="primary"}'] == 1
    assert brs["primary"].state == CLOSED


def test_rate_limit_retry_after_is_honoured():
    p = ScriptedProvider([err("rate_limit", True, retry_after=2.5), "ok"])
    r, _, _, sleeps = make_resilient([Provider("primary", p)])
    assert call(r).text == "ok" and sleeps and sleeps[0] >= 2.5


def test_non_retryable_provider_errors_are_not_retried_and_do_not_open_the_breaker():
    for kind in ("auth", "client", "invalid_response"):
        p = ScriptedProvider([err(kind, False)])
        r, brs, _, sleeps = make_resilient([Provider("primary", p)], threshold=1)
        with pytest.raises(LLMError) as ei:
            call(r)
        assert ei.value.kind == kind and p.calls == 1 and sleeps == [] and brs["primary"].state == CLOSED


def test_breaker_opens_after_outages_then_fails_fast_without_calling_the_provider():
    p = ScriptedProvider([err("server", True)])
    r, brs, m, _ = make_resilient([Provider("primary", p)], threshold=2, attempts=2)
    for _ in range(2):
        with pytest.raises(LLMError):
            call(r)
    assert brs["primary"].state == OPEN
    before = p.calls
    with pytest.raises(CircuitOpen) as ei:
        call(r)
    assert p.calls == before                                    # no call made while open
    assert "circuit breaker is open" in str(ei.value)
    assert m.snapshot()['llm_breaker_rejected_total{provider="primary"}'] == 1
    assert m.snapshot()['llm_breaker_transitions_total{provider="primary",to="open"}'] == 1


def test_half_open_probe_recovers_the_provider():
    clk = Clock()
    p = ScriptedProvider([err("server", True), err("server", True), "recovered"])
    r, brs, _, _ = make_resilient([Provider("primary", p)], clock=clk, threshold=1, attempts=1, cooldown=30)
    with pytest.raises(LLMError):
        call(r)
    assert brs["primary"].state == OPEN
    clk.t += 31
    with pytest.raises(LLMError):                               # probe fails -> open again
        call(r)
    assert brs["primary"].state == OPEN
    clk.t += 31
    assert call(r).text == "recovered" and brs["primary"].state == CLOSED


def test_fallback_provider_is_used_when_primary_fails_or_is_open():
    prim, fb = ScriptedProvider([err("server", True)]), ScriptedProvider(["from-fallback"])
    r, brs, m, _ = make_resilient([Provider("primary", prim), Provider("fallback", fb)], threshold=1, attempts=2)
    out = call(r)
    assert out.text == "from-fallback" and out.provider == "fallback"
    assert brs["primary"].state == OPEN
    pc = prim.calls
    assert call(r).provider == "fallback" and prim.calls == pc  # primary skipped while open
    assert m.snapshot()['llm_fallback_used_total{provider="fallback"}'] == 2


def test_all_providers_failing_raises_the_real_error_not_a_fabricated_answer():
    r, _, _, _ = make_resilient([Provider("primary", ScriptedProvider([err("timeout", True)])),
                                 Provider("fallback", ScriptedProvider([err("server", True)]))], attempts=2)
    with pytest.raises(LLMError) as ei:
        call(r)
    assert ei.value.kind == "server" and ei.value.provider == "fallback"


# ----------------------------------------------------------------- HTTP client error classification
def _client_with(monkeypatch, handler):
    def fake_post(url, headers=None, json=None, timeout=None):
        return handler(url)
    monkeypatch.setattr(httpx, "post", fake_post)
    return OpenAICompatClient("http://llm.test/v1", "k", "m")


def _resp(status, body=None, headers=None):
    return httpx.Response(status, json=body, headers=headers or {}, request=httpx.Request("POST", "http://llm.test"))


@pytest.mark.parametrize("status,kind,retryable", [(429, "rate_limit", True), (500, "server", True),
                                                   (503, "server", True), (401, "auth", False),
                                                   (403, "auth", False), (400, "client", False)])
def test_http_status_classification(monkeypatch, status, kind, retryable):
    c = _client_with(monkeypatch, lambda u: _resp(status, {}, {"retry-after": "4"} if status == 429 else {}))
    with pytest.raises(LLMError) as ei:
        c.complete("r", "s", "u", 5)
    assert (ei.value.kind, ei.value.retryable) == (kind, retryable)
    if status == 429:
        assert ei.value.retry_after == 4.0


def test_timeout_connection_and_malformed_body_classification(monkeypatch):
    def boom(exc):
        def h(u):
            raise exc
        return h
    for exc, kind, ret in [(httpx.ReadTimeout("t"), "timeout", True), (httpx.ConnectError("c"), "connection", True)]:
        with pytest.raises(LLMError) as ei:
            _client_with(monkeypatch, boom(exc)).complete("r", "s", "u", 5)
        assert (ei.value.kind, ei.value.retryable) == (kind, ret)
    with pytest.raises(LLMError) as ei:
        _client_with(monkeypatch, lambda u: _resp(200, {"unexpected": 1})).complete("r", "s", "u", 5)
    assert (ei.value.kind, ei.value.retryable) == ("invalid_response", False)
    ok = _client_with(monkeypatch, lambda u: _resp(200, {"choices": [{"message": {"content": "hi"}}],
                                                        "usage": {"prompt_tokens": 3, "completion_tokens": 1}}))
    r = ok.complete("r", "s", "u", 5)
    assert r.text == "hi" and r.prompt_tokens == 3


# ----------------------------------------------------------------- rate limiting
def test_rate_limiter_window_and_per_client_isolation():
    conn, clk = fakeredis.FakeStrictRedis(), Clock(1000.0)
    ds = [check_rate(conn, "a", 3, 60, clk) for _ in range(4)]
    assert [d.allowed for d in ds] == [True, True, True, False]
    assert ds[3].remaining == 0 and 1 <= ds[3].retry_after <= 60
    assert check_rate(conn, "b", 3, 60, clk).allowed                  # other client unaffected
    clk.t += 60
    assert check_rate(conn, "a", 3, 60, clk).allowed                  # new window


def test_api_returns_meaningful_429(env, conn, monkeypatch):
    from fastapi.testclient import TestClient
    from rq import Queue
    from triage.api.main import create_app
    monkeypatch.setenv("AGENT_MODE", "placeholder")
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "2")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "3600")
    c = TestClient(create_app(settings_factory=Settings, redis_factory=lambda s: conn,
                              queue_factory=lambda s, cn: Queue(s.queue_name, connection=cn)))
    h = {"X-Client-Id": "client-1"}
    assert [c.post("/v1/petitions", json=valid_payload(), headers=h).status_code for _ in range(2)] == [202, 202]
    r = c.post("/v1/petitions", json=valid_payload(), headers=h)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1
    assert r.headers["X-RateLimit-Limit"] == "2" and "Rate limit exceeded" in r.json()["detail"]
    assert c.post("/v1/petitions", json=valid_payload(), headers={"X-Client-Id": "client-2"}).status_code == 202
    assert db.count_runs(Settings().db_path) == 3   # the 429 created no run
    assert "rate_limited_total 1" in c.get("/metrics").text


def test_rate_limit_can_be_disabled(env, conn, monkeypatch):
    from fastapi.testclient import TestClient
    from rq import Queue
    from triage.api.main import create_app
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "1")
    c = TestClient(create_app(settings_factory=Settings, redis_factory=lambda s: conn,
                              queue_factory=lambda s, cn: Queue(s.queue_name, connection=cn)))
    assert all(c.post("/v1/petitions", json=valid_payload()).status_code == 202 for _ in range(3))


# ----------------------------------------------------------------- caches
class CountingEmbedder(HashEmbedder):
    def __init__(self, name="a"):
        super().__init__(name=name)
        self.calls = 0

    def embed(self, texts):
        self.calls += len(texts)
        return super().embed(texts)


def test_embedding_cache_hits_and_key_changes_with_embedding_config():
    conn = fakeredis.FakeStrictRedis()
    m = Metrics(conn)
    e1 = CountingEmbedder("model-a")
    c1 = CachedEmbedder(e1, conn, m)
    v1 = c1.embed(["attendance", "condonation"])
    assert c1.embed(["attendance"]) == [v1[0]] and e1.calls == 2         # second call served from cache
    s = m.snapshot()
    assert s['cache_hits_total{cache="embedding"}'] == 1 and s['cache_misses_total{cache="embedding"}'] == 2
    e2 = CountingEmbedder("model-b")                                       # different embedding config -> new keys
    CachedEmbedder(e2, conn, m).embed(["attendance"])
    assert e2.calls == 1


def test_embedding_cache_survives_redis_failure():
    class Broken:
        def get(self, *a, **k): raise ConnectionError("down")
        def set(self, *a, **k): raise ConnectionError("down")
        def hincrbyfloat(self, *a, **k): raise ConnectionError("down")
    e = CountingEmbedder()
    out = CachedEmbedder(e, Broken(), Metrics(Broken())).embed(["x"])
    assert len(out) == 1 and e.calls == 1


class FakeRetriever:
    def __init__(self):
        self.calls = 0
        self.embedder = HashEmbedder()

    def keyword(self, q, k=5):
        from triage.retrieval.search import RetrievalResult
        self.calls += 1
        return [RetrievalResult(chunk_id="c1", text="t", score=1.0, strategy="keyword",
                                metadata={"doc_name": "d", "chapter": "c", "clause_id": "1", "page_start": 1})]


def test_retrieval_cache_invalidates_when_the_corpus_changes():
    conn, inner, m = fakeredis.FakeStrictRedis(), FakeRetriever(), None
    m = Metrics(conn)
    fp = {"v": "corpusA"}
    r = CachedRetriever(inner, conn, m, "unused", fingerprint=lambda: fp["v"])
    r.keyword("q"); r.keyword("q")
    assert inner.calls == 1                                                # second call is a cache hit
    fp["v"] = "corpusB"                                                    # documents / embedding config changed
    r.keyword("q")
    assert inner.calls == 2                                                # old entry is unreachable: no stale result
    assert invalidate_retrieval(conn) == 2
    fp["v"] = "none"                                                       # unknown corpus version -> never cached
    r.keyword("q"); r.keyword("q")
    assert inner.calls == 4 and m.snapshot()['cache_bypass_total{cache="retrieval"}'] == 2


def test_corpus_fingerprint_changes_with_documents_and_embedding_tag(tmp_path):
    p = str(tmp_path / "f.sqlite3")
    assert corpus_fingerprint(p) == "none"
    base = {"documents": [{"file": "a.pdf", "sha256": "1"}], "embedding_tag": "t1", "chunker_version": "c1", "chunks_total": 5}
    db.save_ingest(p, db.now(), "success", base)
    f1 = corpus_fingerprint(p)
    db.save_ingest(p, db.now(), "success", {**base, "documents": [{"file": "a.pdf", "sha256": "2"}]})
    f2 = corpus_fingerprint(p)
    db.save_ingest(p, db.now(), "success", {**base, "embedding_tag": "t2"})
    f3 = corpus_fingerprint(p)
    db.save_ingest(p, db.now(), "failed", {**base, "embedding_tag": "t3"})   # a failed ingest does not change the version
    assert len({f1, f2, f3}) == 3 and corpus_fingerprint(p) == f3


# ----------------------------------------------------------------- degraded behaviour through the real graph
def test_provider_outage_escalates_with_clear_label_and_no_determination(go):
    prim = ScriptedProvider([err("server", True)])
    r, brs, _, _ = make_resilient([Provider("primary", prim)], attempts=2)
    run, _ = go(None, llm=r)
    assert run["status"] == "escalated"
    res = run["result"]
    assert res["escalation"]["reason"] == "llm_unavailable" and "LLM call failed" in res["escalation"]["detail"]
    assert res["position"] == "NO_DETERMINATION" and res["citations"] == [] and res["route"] == "refer-to-committee"
    assert any(e["event"] == "llm_retry" for e in run["events"])            # retries visible in the run trace


def test_open_breaker_degrades_gracefully(go):
    conn, clk = fakeredis.FakeStrictRedis(), Clock()
    prim = ScriptedProvider(["unused"])
    r, brs, _, _ = make_resilient([Provider("primary", prim)], conn=conn, clock=clk)
    for _ in range(3):
        brs["primary"].record_failure()
    run, _ = go(None, llm=r)
    assert prim.calls == 0                                                 # fail fast: provider never called
    assert run["result"]["escalation"]["reason"] == "llm_unavailable"
    assert "circuit breaker is open" in run["result"]["escalation"]["detail"]
    assert run["result"]["citations"] == []


def test_fallback_provider_produces_a_normal_verified_result(go):
    script = FakeLLM(happy_script(esc={"required": True, "reason": "committee_discretion", "detail": "VC"}))

    class Fallback:
        def complete(self, role, system, user, timeout):
            return script.complete(role, system, user, timeout)
    r, brs, _, _ = make_resilient([Provider("primary", ScriptedProvider([err("timeout", True)])),
                                   Provider("fallback", Fallback())], attempts=1, threshold=1)
    run, _ = go(None, llm=r)
    assert run["status"] == "escalated" and len(run["result"]["citations"]) == 2   # verified citations survive fallback
    assert any(e["event"] == "llm_fallback" for e in run["events"])
    assert all(e["detail"].get("provider") == "fallback" for e in events(run, "llm_call") if e["detail"]["ok"])


# ----------------------------------------------------------------- worker failure handling / stale runs
def test_worker_marks_run_failed_if_the_pipeline_crashes(env, monkeypatch):
    from triage.agents import runtime as rt
    from triage.worker import tasks
    monkeypatch.setenv("AGENT_MODE", "agents")
    s = Settings()
    rid = db.create_run(s.db_path, valid_payload(), None, "c")

    def crash(st, run_id):
        raise MemoryError("worker blew up")
    monkeypatch.setattr(rt, "run_pipeline", crash)
    with pytest.raises(MemoryError):
        tasks.process_petition(rid)
    run = db.get_run(s.db_path, rid)
    assert run["status"] == "failed" and "worker blew up" in run["error"]


def test_stale_running_run_is_marked_failed_on_read(env, conn, monkeypatch):
    from fastapi.testclient import TestClient
    from rq import Queue
    from triage.api.main import create_app
    s = Settings()
    rid = db.create_run(s.db_path, valid_payload(), None, "c")
    db.set_status(s.db_path, rid, "running")
    c = TestClient(create_app(settings_factory=Settings, redis_factory=lambda st: conn,
                              queue_factory=lambda st, cn: Queue(st.queue_name, connection=cn)))
    assert c.get(f"/v1/runs/{rid}").json()["status"] == "running"          # fresh: left alone
    import triage.api.main as api
    monkeypatch.setattr(api, "stale_after_seconds", lambda st: -1)
    body = c.get(f"/v1/runs/{rid}").json()
    assert body["status"] == "failed" and "worker stopped responding" in body["error"]


def test_metrics_endpoint_exposes_run_and_escalation_counters(env, conn, monkeypatch):
    from fastapi.testclient import TestClient
    from rq import Queue, SimpleWorker
    from triage.api.main import create_app
    monkeypatch.setenv("AGENT_MODE", "placeholder")
    monkeypatch.setenv("PLACEHOLDER_DELAY_SECONDS", "0")
    c = TestClient(create_app(settings_factory=Settings, redis_factory=lambda s: conn,
                              queue_factory=lambda s, cn: Queue(s.queue_name, connection=cn)))
    c.post("/v1/petitions", json=valid_payload())
    SimpleWorker([Queue("petitions", connection=conn)], connection=conn).work(burst=True)
    text = c.get("/metrics").text
    assert 'runs_total{status="completed"} 1' in text and "run_seconds_count" in text
    assert "queue_wait_seconds_count" in text and 'runs_in_state{status="completed"} 1' in text


# --- real-provider findings (hosted model), see PROJECT_STATUS.md ---
def test_client_appends_plain_json_note_and_parses_try_again_hint(monkeypatch):
    import httpx
    from triage.llm import client as C
    seen = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen["sys"] = json["messages"][0]["content"]
        req = httpx.Request("POST", url)
        if len(seen) == 1:
            return httpx.Response(429, request=req, text='{"error":{"message":"Rate limit. Please try again in 1m2.5s."}}')
        return httpx.Response(400, request=req, json={"error": {"message": "Tool choice is none, but model called a tool KEY123"}})

    monkeypatch.setattr(C.httpx, "post", fake_post)
    cl = C.OpenAICompatClient("http://x/v1", "KEY123", "m")
    with pytest.raises(C.LLMError) as ei:
        cl.complete("triage", "SYSTEM", "user", 5)
    assert ei.value.kind == "rate_limit" and ei.value.retry_after == 62.5
    assert seen["sys"].startswith("SYSTEM") and "NO native function-calling" in seen["sys"]
    seen["x"] = 1
    with pytest.raises(C.LLMError) as ei:
        cl.complete("triage", "SYSTEM", "user", 5)
    assert ei.value.kind == "model_tool_call" and ei.value.retryable          # stochastic model glitch: retried, not an outage
    assert "Tool choice is none" in str(ei.value) and "KEY123" not in str(ei.value)
    from triage.reliability.resilient_llm import OUTAGE_KINDS
    assert "model_tool_call" not in OUTAGE_KINDS                              # never opens the circuit breaker


def test_null_escalation_detail_from_model_is_accepted():
    from triage.agents.state import VerifierLLMOutput
    o = VerifierLLMOutput.model_validate({"route": "refer-to-committee", "position": "Referred.", "basis": "see E1",
                                          "escalation": {"required": False, "reason": None, "detail": None}})
    assert o.escalation.detail == ""


def test_client_paces_itself_from_ratelimit_headers_instead_of_burning_a_429(monkeypatch):
    import httpx
    from triage.llm import client as C
    C._pace.clear()
    sleeps = []
    monkeypatch.setattr(C.time, "sleep", lambda s: sleeps.append(s))
    hdr = {"x-ratelimit-remaining-tokens": "300", "x-ratelimit-limit-tokens": "6000"}      # 100 tokens/s refill

    def fake_post(url, headers=None, json=None, timeout=None):
        return httpx.Response(200, request=httpx.Request("POST", url), headers=hdr,
                              json={"choices": [{"message": {"content": "{}"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}})

    monkeypatch.setattr(C.httpx, "post", fake_post)
    cl = C.OpenAICompatClient("http://pace/v1", "k", "m")
    cl.complete("t", "S" * 100, "U" * 3000, 5)          # first call: nothing known yet -> no wait
    assert sleeps == []
    cl.complete("t", "S" * 100, "U" * 3000, 5)          # ~1.5k tokens needed, 300 left -> waits ~12 s, capped at 30
    assert len(sleeps) == 1 and 8 < sleeps[0] <= C.PACE_MAX_WAIT
    sleeps.clear(); C._pace["http://pace/v1"] = (6000.0, 6000.0, C.time.time())             # full bucket -> no wait
    cl.complete("t", "S", "U", 5)
    assert sleeps == []


def test_stale_threshold_follows_the_run_budget(monkeypatch):
    from triage.api.main import stale_after_seconds
    monkeypatch.setenv("MAX_RUN_SECONDS", "120")
    assert stale_after_seconds(Settings()) == 300                      # job timeout (180) + 2 min
    monkeypatch.setenv("MAX_RUN_SECONDS", "20")
    assert stale_after_seconds(Settings()) == 240                      # floor
    monkeypatch.setenv("MAX_RUN_SECONDS", "450")
    assert stale_after_seconds(Settings()) == 450 + 60 + 120           # follows the budget


def test_quota_429_fails_fast_with_the_providers_explanation_and_counts_as_an_outage(monkeypatch):
    """Real-provider finding: a tokens-per-DAY 429 asked for ~8 minutes; retrying every 30 s only burned the run budget."""
    import httpx
    from triage.llm import client as C
    from triage.reliability.resilient_llm import OUTAGE_KINDS

    def fake_post(url, headers=None, json=None, timeout=None):
        return httpx.Response(429, request=httpx.Request("POST", url), headers={"retry-after": "467"},
                              json={"error": {"message": "Rate limit reached on tokens per day (TPD): Limit 200000. Please try again in 7m46.992s. SECRETKEY"}})

    monkeypatch.setattr(C.httpx, "post", fake_post)
    with pytest.raises(C.LLMError) as ei:
        C.OpenAICompatClient("http://q/v1", "SECRETKEY", "m").complete("t", "s", "u", 5)
    e = ei.value
    assert e.kind == "quota" and e.retryable is False and e.retry_after == 467
    assert "tokens per day" in str(e) and "SECRETKEY" not in str(e)
    assert "quota" in OUTAGE_KINDS                               # opens the breaker so later runs fail fast too


def test_short_429_is_still_retried(monkeypatch):
    import httpx
    from triage.llm import client as C

    def fake_post(url, headers=None, json=None, timeout=None):
        return httpx.Response(429, request=httpx.Request("POST", url), headers={"retry-after": "5"}, json={"error": {"message": "slow down"}})

    monkeypatch.setattr(C.httpx, "post", fake_post)
    with pytest.raises(C.LLMError) as ei:
        C.OpenAICompatClient("http://q/v1", "k", "m").complete("t", "s", "u", 5)
    assert ei.value.kind == "rate_limit" and ei.value.retryable is True


# ---- outage behaviour found by loadtest/failure_drills.py against real stopped containers ----
class _SlowDeadRedis:
    """A Redis whose every call fails after a delay, like an unreachable host with a connect timeout."""
    calls = 0

    def __getattr__(self, name):
        def f(*a, **k):
            _SlowDeadRedis.calls += 1
            time.sleep(0.4)
            raise ConnectionError("redis unreachable")
        return f


def test_api_stays_responsive_while_redis_is_down_and_fails_fast(env):
    from fastapi.testclient import TestClient
    from rq import Queue
    from triage.api.main import create_app
    from triage.reliability import deps
    deps.reset_redis_state()
    dead = _SlowDeadRedis()
    c = TestClient(create_app(settings_factory=Settings, redis_factory=lambda st: dead,
                              queue_factory=lambda st, cn: Queue(st.queue_name, connection=cn)))
    t0 = time.time(); r = c.get("/readyz"); first = time.time() - t0
    assert r.status_code == 503 and r.json()["checks"]["redis"].startswith("down") and "redis_down" in r.json()["checks"]["degraded"]
    assert first < 3                                             # one probe, not one per check
    t0 = time.time()
    for _ in range(5):
        assert c.get("/healthz").status_code == 200              # liveness never depends on Redis
    assert time.time() - t0 < 1.0                                # and is not slowed by metrics timeouts
    t0 = time.time(); p = c.post("/v1/petitions", json=valid_payload()); dt = time.time() - t0
    assert p.status_code == 503 and "queue unavailable" in p.json()["detail"] and dt < 1.0   # clear and fast, nothing silently dropped
    calls_before = _SlowDeadRedis.calls
    for _ in range(10):
        c.get("/readyz")
    assert _SlowDeadRedis.calls == calls_before                  # the down window suppresses further attempts
    deps.reset_redis_state()                                     # window over: the next request tries Redis again
    assert c.get("/readyz").status_code == 503 and _SlowDeadRedis.calls > calls_before


def test_metrics_do_not_block_while_redis_is_down():
    from triage.reliability import deps
    from triage.reliability.metrics import Metrics
    deps.reset_redis_state()
    m = Metrics(_SlowDeadRedis())
    m.inc("x")                                                   # first failure marks Redis down
    t0 = time.time()
    for _ in range(50):
        m.inc("x"); m.observe("y", 1.0)
    assert time.time() - t0 < 0.2
    deps.reset_redis_state()


def test_readiness_counts_only_workers_with_a_recent_heartbeat(monkeypatch):
    from datetime import datetime, timedelta, timezone
    import rq
    from triage.api.main import live_worker_count
    now = datetime.now(timezone.utc)

    class W:
        def __init__(self, age):
            self.last_heartbeat = None if age is None else now - timedelta(seconds=age)

    monkeypatch.setattr(rq.Worker, "all", classmethod(lambda cls, connection=None, **k: [W(5), W(40), W(300), W(None), W(2000)]))
    assert live_worker_count(object()) == 2                      # killed workers stay registered for minutes: not counted


def test_chroma_failing_during_citation_verification_is_a_retrieval_outage_not_an_unknown_error(go, retriever):
    """Cached research results can hide a Chroma outage until the verifier re-reads the live index."""
    class IndexDownAtVerify:
        def __init__(self, inner): self.inner = inner
        def __getattr__(self, n): return getattr(self.inner, n)
        def get_chunk(self, chunk_id): raise ConnectionError("chroma unreachable")

    run, _ = go(happy_script(), retr=IndexDownAtVerify(retriever))
    res = run["result"]
    assert run["status"] == "escalated" and res["escalation"]["reason"] == "retrieval_unavailable"
    assert res["position"] == "NO_DETERMINATION" and res["citations"] == []
