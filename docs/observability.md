# Observability (Phase 6)

What is verified: unit/integration tests (`tests/test_observability.py`, in-memory OpenTelemetry exporter, fakeredis) and the Docker run recorded in `PROJECT_STATUS.md`.
Dashboards were provisioned and queried through the Grafana/Prometheus HTTP APIs and Jaeger showed a 12-span API+worker trace; **the Grafana dashboard itself has not been viewed in a browser**.

## Logs
`observability/logging_setup.py`: one JSON object per line — `ts, level, service, logger, message, correlation_id, run_id` + structured extras. A redaction filter masks bearer tokens,
`sk-…` keys, `api_key=…` assignments and the literal values of `LLM_API_KEY` / `FALLBACK_LLM_API_KEY`; fields named `petition_text`/`petition` are dropped; exceptions are logged as
type + message only (no stack locals). The code base never logs petition text. Health/readiness/metrics requests are not logged.

## Correlation IDs
The API middleware accepts `X-Correlation-ID` (or generates one), puts it in a context variable, returns it in the response header, stores it on the run (`queued` event and `runs.correlation_id`),
and the worker restores it from the run row, so API logs, worker logs and `run_events` share one id. Test: `test_correlation_id_flows_from_request_to_run_events_worker_logs_and_response`.

## Tracing (OpenTelemetry → Jaeger)
Enabled by `OTEL_EXPORTER_OTLP_ENDPOINT` (e.g. `http://jaeger:4318`); otherwise a no-op. Spans: `POST /v1/petitions` (HTTP, route template as name) → (W3C `traceparent` passed as a job argument) →
`worker.process_petition` → `agent.triage|research|verifier` → `llm.call` (model, provider, tokens) and `tool.<name>`. Attributes are restricted to short primitives; keys containing
`petition_text`, `api_key`, `authorization`, `password`, `secret` are dropped (tested). Jaeger UI: http://localhost:16686 (profile `observability`).

## Metrics and dashboards
API `GET /metrics` renders counters/histograms that API **and workers** write into Redis (workers are separate processes), plus gauges computed on scrape (queue depth, active workers,
breaker state, runs by state). Prometheus (http://localhost:9090) scrapes it every 5 s and also cAdvisor (container CPU/memory). Grafana (http://localhost:3000, admin credentials from
`.env`, default `admin/admin` for local demo only) loads `observability/grafana/dashboards/triage.json`: 18 panels — runs/min by status, end-to-end p50/p95, error rate, escalations by
reason, queue wait p95, queue depth/workers, per-agent executions and p95, tool calls/latency, LLM calls by provider/outcome, retries/fallbacks/breaker rejections, breaker state, cache hit
ratio, HTTP rate/latency, rate-limited requests, container CPU and memory.

## Run trace
`GET /v1/runs/{id}/trace` rebuilds the run from persisted `run_events` (works even with tracing off): timeline, per-agent runs/failures/seconds/LLM calls/tool calls, LLM call table (provider,
model, tokens, latency, error), retrieval history (tool, arguments, clauses, pages, scores), retries/fallbacks, outcome and prompt versions. The UI **Run status** page shows these as tabs.

## Health and readiness
`/healthz` = process alive. `/readyz` = 200 only if Redis and SQLite respond, and reports Chroma (`ok|down|not-configured`), active worker count, LLM configured or not, breaker state, queue,
and a human-readable `degraded` list (e.g. `no_workers; llm_not_configured: petitions escalate with reason llm_unavailable; chroma_down: retrieval unavailable`). Readiness stays 200 when only
optional dependencies are degraded, because the service still accepts and safely escalates petitions.

## Limits
Histogram buckets are fixed (0.1 … 120 s); quantiles from Prometheus are bucket interpolations. Redis-hash metrics are cumulative and are not reset on restart (use `rate()`). cAdvisor needs
host cgroup access (`privileged`), which is why the observability stack is opt-in. Traces are exported with a batch processor; spans in flight when a container is killed are lost.
