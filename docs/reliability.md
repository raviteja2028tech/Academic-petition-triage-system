# Reliability, resilience and cost control (Phase 4)

All behaviour below is covered by deterministic tests in `tests/test_reliability.py` (fake clocks, recorded sleeps, seeded RNG, scripted providers,
fakeredis). It has **not** been exercised against a real LLM provider; the Docker fault-injection run (stub LLM) is reported in `docs/LOAD_TEST.md`.

## LLM call path
`AgentContext.call_json → ResilientLLM.complete → [per provider] breaker.allow? → retry(OpenAICompatClient.complete)`
* **Timeouts**: every LLM call has `LLM_TIMEOUT_SECONDS` (clipped to the remaining run budget); every retrieval tool call runs in a thread with
  `TOOL_TIMEOUT_SECONDS`; the whole run is bounded by `MAX_RUN_SECONDS`.
* **Error classification** (`llm/client.py`): `timeout`, `connection`, `rate_limit` (429, honours `Retry-After`), `server` (5xx) are **retryable**;
  `auth` (401/403), `client` (other 4xx) and `invalid_response` (unusable body) are **not**.
* **Retry** (`reliability/retry.py`): at most `LLM_MAX_ATTEMPTS` (3) tries per provider; exponential backoff with full jitter
  `U(0, min(cap, base·2^(n-1)))` (`LLM_BACKOFF_*`); a provider `Retry-After` is a lower bound (capped). It never sleeps past the run's remaining time
  (it raises the real error instead). Non-retryable errors are raised on the first failure and are never retried.
* **Circuit breaker** (`reliability/breaker.py`): Redis-backed, shared by all workers, per provider. `closed → open` after `BREAKER_FAILURE_THRESHOLD`
  consecutive outage failures (retries already exhausted); `open` rejects without calling the provider until `BREAKER_COOLDOWN_SECONDS`; then `half_open`
  admits **one** probe at a time (`SET NX` with expiry so a crashed probe cannot wedge it); success closes, failure re-opens. Only outage kinds count —
  bad credentials or a malformed request do not open the breaker.
* **Fallback provider**: optional `FALLBACK_LLM_*`. Used only when the primary fails or its breaker is open; each provider has its own breaker. The result
  records which provider answered (`llm_call.provider`) and a `llm_fallback` event.
* **Graceful degradation**: if no provider can answer, the original error (or `CircuitOpen`) propagates and the graph ends the run `escalated` with reason
  `llm_unavailable`, `position: NO_DETERMINATION`, no citations, and a plain-language detail (e.g. "circuit breaker is open … no reliable reasoning is
  available"). Nothing is fabricated or served from a stale cache.
* **Not retried / not cached by design**: invalid model output gets one *repair* re-prompt (that is a different mechanism from transport retry) and then
  `invalid_agent_output`; LLM responses are never cached (a cached determination could be stale or detached from the verified evidence).

## Worker failure handling
* `process_petition` wraps the pipeline: an unexpected exception marks the run `failed` (unless it already reached a terminal state) and re-raises so RQ records the failure.
* RQ kills a job at `job_timeout=300` without running our code; a run left `running` for > 600 s is marked `failed` ("worker stopped responding") the next time it is read
  (`GET /v1/runs/{id}`), so clients are not left polling forever. Documented limitation: there is no background reaper; unread stale runs stay `running`.
* Status lifecycle `queued → running → completed | escalated | failed`; every transition is an event.

## Rate limiting
Redis fixed-window counter per client (`X-Client-Id`, else the peer address) on `POST /v1/petitions`: `RATE_LIMIT_REQUESTS` per `RATE_LIMIT_WINDOW_SECONDS` (30/60 s).
Excess requests get **HTTP 429** with `Retry-After`, `X-RateLimit-Limit`, `X-RateLimit-Remaining: 0` and a plain-language body; no run row or job is created. If Redis is
unavailable the limiter fails open (and the queue check then returns 503). Fixed windows allow a burst of up to 2× the limit across a window boundary — acceptable here, noted.

## Caching (`reliability/cache.py`)
| Cache | Key | Invalidation |
|---|---|---|
| Query embeddings | `emb:<sha(embedder tag)>:<sha(text)>`; tag = model name + dimension + normalisation + chunker version | a different embedding config can never read old vectors; TTL |
| Retrieval results (semantic, keyword, clause) | `ret:<corpus fingerprint>:<sha(request)>`; fingerprint = source-document SHA-256s + embedding tag + chunker version + chunk count of the last **successful** ingestion | changed documents / embedding config / chunker → new fingerprint (old entries unreachable); `ingest` also deletes all `ret:*`; fingerprint `none` (never ingested) → cache bypassed; TTL |
`get_chunk` (used by citation verification) is **never** cached — verification always re-reads the live index. Prompt versions are not in these keys because prompts do not
influence retrieval; they are recorded per run. Redis errors fall through to the real computation (counted as `cache_errors_total`).

## Metrics (Redis hash → Prometheus text at `GET /metrics`)
`llm_calls_total{provider,outcome}`, `llm_retries_total{provider,kind}`, `llm_fallback_used_total`, `llm_breaker_transitions_total{provider,to}`, `llm_breaker_rejected_total`,
`llm_breaker_state` (gauge), `llm_call_seconds`, `cache_hits_total / cache_misses_total / cache_bypass_total / cache_errors_total{cache}`, `rate_limited_total`,
`runs_total{status}`, `run_seconds`, `queue_wait_seconds`, `escalations_total{reason}`, `agent_runs_total{agent,outcome}`, `agent_seconds`, `tool_calls_total{tool,ok}`, `tool_seconds`,
`http_requests_total`, `http_request_seconds`, `queue_depth`, `workers_active`, `runs_in_state`. Metric writes swallow Redis errors so metrics can never break a run.

## Cost control
Per-call token counts are provider-reported when available, otherwise estimated (chars/4) and labelled; cost needs configured prices (`PRICE_*_PER_1K`) else it is
reported as **unknown** (never 0). Per-run `cost` block, per-call cost in `llm_call` events, `/v1/stats` aggregates and "cost per 100 runs". Bounds on cost: `MAX_RESEARCH_STEPS`,
`MAX_TOOL_CALLS`, `MAX_VERIFY_RETRIES`, per-provider attempts, rate limit, and unsupported/unsafe petitions are escalated **before** most LLM calls (injection/toxicity: none; unsupported types: only triage).

## Known gaps
No background stale-run reaper; no per-provider rate-limit budgeting beyond `Retry-After`; no request hedging; the fixed-window limiter is coarse; the breaker is per provider, not per model;
retry/breaker behaviour against a real provider's failure modes is untested.
