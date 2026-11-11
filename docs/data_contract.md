# Data contract (D1)

Single source of truth: `src/triage/contracts.py` (Pydantic v2). Live schema: `GET /openapi.json`, UI: `GET /docs`.
All data is **synthetic**. No real student data may be submitted.

## `POST /v1/petitions` → 202 | 422 | 503
Headers (optional): `X-Client-Id`, `X-Correlation-ID`.

| Field | Type / rule |
|-------|-------------|
| `student_ref` | string, regex `^SYN-\d{6}$` (real-looking ids are rejected) |
| `program` | string, 2–60 chars |
| `admission_batch` | string, regex `^\d{4}-\d{2}$` (e.g. `2025-26`) |
| `petition_type` | enum: `attendance`, `re-evaluation`, `re-registration`, `medical-leave`, `grade-grievance` |
| `course_code` | `^[A-Za-z0-9]{3,12}$` |
| `semester` | int 1–8 |
| `classes_held` / `classes_attended` | optional ints (held 1–1000, attended ≥0); must be supplied together |
| `attendance_percentage` | optional float 0–100 |
| `reason_category` | enum: `medical`, `personal`, `sports-cultural`, `other` |
| `medical_documentation` | enum: `none` (default), `certificate`, `hospital-record` |
| `period_start`, `period_end` | optional ISO dates |
| `petition_text` | string, 20–2000 chars |
| *(any other field)* | rejected (`extra=forbid`) |

Cross-field rules: `classes_attended ≤ classes_held`; if counts and percentage are all given, percentage must equal attended/held within ±0.5; `period_start ≤ period_end`; an `attendance` petition needs a percentage or counts.

**Deliberately not validated here:** the attendance minimum, condonation limits or any other academic rule. Those come from the retrieved regulations (Phase 3), not from input validation.

Responses
* `202` `{run_id, status:"queued", status_url}`; the request returns before any processing.
* `422` `{detail, quarantine_id, errors:[{field, rule, message}]}`; payload hash, timestamp and errors are stored in `quarantine`; **no run row and no queue job are created**.
* `503` queue (Redis) unavailable; if a run row was already written it is marked `failed`.

## `GET /v1/runs/{run_id}`
`{run_id, status, created_at, updated_at, petition_type, student_ref, mode, result, error, events[]}`
Status lifecycle: `queued → running → completed | escalated | failed`. 404 for unknown ids.

With `AGENT_MODE=placeholder` the `result` is a **placeholder**: `{mode:"placeholder", evidence_used:false, route:null, position:"NO_DETERMINATION", citations:[], escalation:{required:false,reason:null}, message, disclaimer}`. It makes no determination.

## Other endpoints
| Endpoint | Purpose |
|----------|---------|
| `GET /v1/runs?limit=` | counts per status + recent runs |
| `GET /v1/quarantine?limit=` | recent rejected payloads with field errors |
| `GET /v1/corpus` | real index state: sources, chunks, last ingest, errors, verified-passage checks, difficult-case status; `ready` is true only if the last ingestion succeeded, chunks > 0 and Chroma is reachable |
| `GET /healthz` | liveness |
| `GET /readyz` | 200 if Redis and SQLite are OK, else 503; also reports Chroma (`ok`/`down`/`not-configured`, informational) |

### Added in Phases 4-6
| Endpoint | Purpose |
|----------|---------|
| `POST /v1/petitions` | now also `429` when the per-client rate limit is exceeded: `{detail, retry_after_seconds}` + headers `Retry-After`, `X-RateLimit-Limit`, `X-RateLimit-Remaining`; no run is created. Every response carries `X-Correlation-ID` (the request's, or generated). |
| `GET /v1/runs/{id}/trace` | run reconstructed from persisted events: `{run_id, correlation_id, status, total_seconds, outcome, agents{agent: runs, failures, seconds, llm_calls, tool_calls}, llm_calls[], retrieval_history[], retries_and_fallbacks[], retry_count, prompt_versions, timeline[]}` |
| `POST /v1/runs/{id}/feedback` | body `{rating: 1..5, agrees_with_recommendation?: bool, comment?: <=500 chars}` (`extra=forbid`); one entry per (run, `X-Client-Id`), later calls update it; `404` unknown run, `409` run not finished, `422` invalid |
| `GET /v1/feedback` | `{stats: {count, mean_rating, satisfaction_rate (rating>=4), distribution, agreement_rate, agreement_count}, recent[]}` |
| `GET /v1/stats` | outcomes, escalation reasons, latency p50/p95, token totals, **estimated** cost (`usd_per_100_runs` is `null` when no price is configured), sampled LLM-judge averages, feedback |
| `GET /v1/evaluation` | evaluation reports found in `EVAL_RESULTS_DIR`, labelled by mode (`scripted` vs `real`), plus the retrieval experiment |
| `GET /metrics` | Prometheus text (counters/histograms written by API and workers into Redis + queue depth, workers, breaker state, runs by state) |
| `GET /readyz` | `checks`: `redis`, `database`, `chroma`, `workers`, `llm` (configured / not-configured), `llm_breaker` (closed/half_open/open), `degraded` (human-readable list). Status 200 iff Redis and the database respond. |

## Run `result` in agent mode (Phase 3)
`{mode:"agents", route, position, basis, citations[], escalation{required, reason, detail}, evidence_reviewed[{evidence_id, chunk_id, clause_id, page}], triage, prompt_versions, agent_stats, usage, cost, disclaimer, message}`
* `route` is one of `grant-under-provision | refer-to-committee | reject`. When no determination exists, `position` is `NO_DETERMINATION`, `citations` is empty and `route` is `refer-to-committee` (a human decides).
* `citations[]`: `{evidence_id, chunk_id, document, chapter, clause_id, page, quote, verified:true}`; only verified citations are ever returned.
* `escalation.reason`: `corpus_insufficient, conflicting_provisions, committee_discretion, unsupported_petition_type, petition_inconsistent, verification_failed, budget_exhausted, invalid_agent_output, agent_error, llm_unavailable, retrieval_unavailable, output_blocked, petition_ambiguous, unsafe_input` (`unsafe_input` = petition text flagged by the heuristic injection/toxicity checks; it was not sent to a model).
* Status: `completed` (reject / direct grant with verified citations) or `escalated` (`escalation.required`).
* `llm_models`: names of the model(s) that actually answered in this run (the UI warns when the name indicates a stub/scripted model).
* `cost`: `{llm_calls, prompt_tokens, completion_tokens, token_source: reported|estimated|mixed|none, estimated_cost_usd (null if no price configured), pricing: configured|unavailable, note, by_agent{}}`. Cost is always an estimate; unknown is `null`, never 0.
* `llm_call` events additionally carry `provider`, `token_source`, `cost_usd`; new events: `llm_retry`, `llm_fallback`, `llm_skipped`, `guardrail` (`stage: input|output|numeric_claims`, findings).
