# Runbook

Each failure mode lists **Symptom → Confirm → Recover → Verify**. Scenarios A and B are the two required by the assignment (D8); C–E are additional. The
"Exercised" line says whether the procedure was actually run against the Docker stack and what happened (see `PROJECT_STATUS.md` for evidence).

## Start / stop
```bash
cp .env.example .env            # first time only
docker compose up -d --build    # all services (observability/loadtest are opt-in profiles)
docker compose ps               # all healthy; `ingest` exits 0 after indexing
docker compose down             # keep data;  `docker compose down -v` deletes all volumes
```

## A. LLM provider outage / rate limiting (retries, breaker, fallback)
**Symptom.** Runs finish `escalated` with reason `llm_unavailable` and `NO_DETERMINATION`; UI *Health & feedback* shows the breaker `open` and `degraded: llm_circuit_open`; Grafana panel "Circuit breaker state" = 2.
**Confirm.**
1. `curl -s localhost:8000/readyz | python -m json.tool` → `checks.llm_breaker` (`closed` / `half_open` / `open`), `checks.llm` (`configured` / `not-configured`).
2. `docker compose logs worker | grep -E '"llm_retry"|llm_skipped|circuit'` and the run's trace: `curl localhost:8000/v1/runs/<id>/trace` → `retries_and_fallbacks`, `llm_calls[].error`.
3. Is the provider itself down or rejecting us? `curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $LLM_API_KEY" "$LLM_BASE_URL/models"` (401/403 = credentials, 429 = quota, 5xx/timeout = provider).
**Recover.**
* Credentials (401/403 are *not* retried and do not open the breaker): fix `LLM_API_KEY` in `.env`, then `docker compose up -d worker`.
* Provider down or throttling: nothing to do for correctness — the system already retries with backoff and then escalates without a determination. Optionally configure `FALLBACK_LLM_*` and `docker compose up -d worker`.
* The breaker re-tests the provider by itself after `BREAKER_COOLDOWN_SECONDS` (30 s) with one probe. To force a retest now: `docker compose exec redis redis-cli del cb:primary cb:primary:probe`.
* Re-submit the petitions that escalated with `llm_unavailable` (they are not retried automatically: a human already sees them as unresolved).
**Exercised (2026-10-28, Docker, LLM stub returning HTTP 500):** retries, then breaker `open`, later runs failed fast as `llm_unavailable`; `/readyz` showed `llm_breaker: open`; recovery by restoring the stub and `redis-cli del cb:primary cb:primary:probe` returned the breaker to `closed`. Real-provider outages and the fallback path were NOT exercised.
**Verify.** `readyz` shows `llm_breaker: closed`; a new petition finishes with citations; `llm_calls_total{outcome="ok"}` rises in Prometheus.

## B. Queue backlog / workers not processing
**Symptom.** Runs stay `queued`; UI progress bar stuck on "Queued"; Grafana "Queue depth" rising or "workers" = 0; `/readyz` `degraded: no_workers`.
**Confirm.**
1. `docker compose ps worker` and `docker compose logs --tail 50 worker` (crash loop? cannot reach Redis/Chroma?).
2. `curl -s localhost:8000/metrics | grep -E 'queue_depth|workers_active'`; or `docker compose exec redis redis-cli llen rq:queue:petitions`.
3. Runs stuck in `running` longer than 10 min mean a worker died mid-job; reading them (`GET /v1/runs/<id>`) marks them `failed` ("worker stopped responding").
**Recover.** `docker compose up -d --scale worker=3` (add workers) or `docker compose restart worker`. Jobs persist in Redis (AOF) and runs in SQLite, so queued work resumes. For a poison petition that keeps killing workers, find its run id in the worker log, then `docker compose exec redis redis-cli lrem rq:queue:petitions 0 <run_id>` and mark it failed by reading it after the stale window.
**Exercised:** NOT run against Docker (queue-key names and the poison-job `lrem` step are untested). Worker scaling to 1/2/3 was exercised by the benchmark.
**Verify.** `queue_depth` falls to 0, queued runs reach a terminal state, `workers_active` ≥ 1.

## C. Corpus not ready / Chroma down
**Symptom.** `/v1/corpus` `ready=false`; runs escalate `retrieval_unavailable` or `corpus_insufficient`; `/readyz` `degraded: chroma_down`.
**Confirm.** `curl localhost:8000/v1/corpus` (`message`, `errors`); `docker compose ps chroma`; `docker compose logs ingest`.
**Recover.** `docker compose up -d chroma`; `docker compose run --rm ingest` (idempotent; first run downloads the embedding model, needs network; `EMBED_MODEL` must be set). Full rebuild: `docker compose run --rm ingest python -m triage.retrieval.ingest --force-rebuild`. The retrieval cache is invalidated automatically by ingestion.
**Verify.** `ready=true`, chunk count > 0, all verified-passage checks `found`.

## D. Clients receive HTTP 429
**Symptom.** `POST /v1/petitions` → 429 `Rate limit exceeded … Retry in Ns`. **Confirm.** `Retry-After` header; `rate_limited_total` in `/metrics`. **Recover.** Clients wait `Retry-After`; to raise the limit set `RATE_LIMIT_REQUESTS` / `RATE_LIMIT_WINDOW_SECONDS` and `docker compose up -d api`. The limiter is keyed on `X-Client-Id` (self-asserted) or the peer address.

## E. UI says "Backend unavailable"
`docker compose ps api` → `docker compose logs api` → `curl localhost:8000/readyz` (which check is `down`) → `docker compose restart redis api`.

## Diagnostics
```bash
docker compose run --rm ingest python -m triage.retrieval.search "minimum attendance" -k 5
docker compose run --rm ingest python -m triage.retrieval.search 25OB10.0 --strategy clause
docker compose logs worker | grep <correlation-id>        # one id follows a petition through API, worker and run_events
curl localhost:8000/v1/stats                                # outcomes, escalation reasons, latency, estimated cost
```

## Tests
```bash
python -m pytest -q   |   EMBED_MODEL=<model> python -m pytest -q -m realmodel   |   python scripts/check_no_secrets.py
```
