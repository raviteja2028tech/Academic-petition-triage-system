# Architecture — as implemented through Phase 6

```
Browser → ui (Streamlit) → api (FastAPI) → redis (RQ queue) → worker ×N → SQLite volume
                              │                                   │
                              └──── SQLite (runs, quarantine, ingest manifests)
ingest (one-shot) → parse/chunk/embed → chroma (vectors)         worker (agents) and ingest ↔ chroma
```

| Service | Role | Why a separate boundary |
|---------|------|-------------------------|
| `ui` | Streamlit; calls only the REST API | independent release; UI crash does not stop runs |
| `api` | validation, quarantine, enqueue, status, corpus status | light image (no torch); stays responsive while workers are busy |
| `worker` | executes jobs (placeholder in Phase 1/2) | scalable (`--scale worker=3`), heavy image |
| `redis` | queue | shared state for scaled workers |
| `chroma` | vector store server | shared by workers/ingest, own volume |
| `ingest` | one-shot indexer | run-to-completion lifecycle, re-runnable |

Persistence: named volumes `app_data` (SQLite, WAL), `chroma_data`, `redis_data` (AOF), `hf_cache` (embedding model).

Async model: `POST /v1/petitions` validates, writes a `queued` run, enqueues an RQ job and returns 202; the worker flips `running → completed|failed` and records each transition in `run_events`. The client polls `GET /v1/runs/{id}` (polling chosen over callbacks: simplest, works through NAT, client-driven).

Placeholder mode: `AGENT_MODE=placeholder` (explicit opt-in, used only by the Phase 1 plumbing tests) sleeps and stores `NO_DETERMINATION`. The default `AGENT_MODE=agents` runs the pipeline below.

Phases 4-6 add the layers described at the end of this file (reliability, guardrails/evaluation/feedback/cost, observability). Load testing (Phase 7): `docs/LOAD_TEST.md`.


## Phase 3 — agent pipeline (`src/triage/agents/`, LangGraph)

```
START -> triage -> (unsupported / inconsistent? -> finalize)
                   research <-> verify -> finalize -> END        (verify -> research = bounded retry)
```
Worker job -> `agents.runtime.run_pipeline` -> `graph.build_graph(ctx).invoke(...)` -> result + final status persisted. The API is unchanged; the UI renders the new result.

| Agent | File | Responsibility | Tools | Hand-off object |
|-------|------|----------------|-------|-----------------|
| Triage | `triage_agent.py` | classify type, extract facts, flag mismatches; attendance % comes from the structured fields, never from free text | none (petition is in its prompt) | `TriageResult` |
| Research | `research_agent.py` + `tools.py` | LLM-driven loop that **chooses** the next tool: `search_semantic`, `search_keyword` (BM25), `get_clause`, `get_neighbouring_clauses`, `get_petition_fields`, `finish`; prompted to fetch the base rule, then search for modifying provisions with a query derived from what it read | all of the above | `EvidenceBundle` (passages with evidence ids, queries, stop reason) |
| Verifier/Adjudicator | `verifier_agent.py` + `citations.py` | judges only the evidence; every citation is checked (evidence id was retrieved this run, claimed clause matches, quote is a verbatim excerpt of the passage, passage re-read from Chroma and unchanged); applies authority and output rules; retry or escalate | read-only index re-check | `Determination` (route, position, basis, verified citations, escalation) |

Citation fields (`document, chapter, clause_id, page`) are filled from the index, not from model text; only the quote is the model's, and it must match verbatim.

Rules enforced in code (not only in prompts): `reject` / `grant-under-provision` need at least one verified citation; a grant resting on a passage that reserves the decision to an authority (e.g. "may be condoned by the Vice-Chancellor") is downgraded to `refer-to-committee` with reason `committee_discretion`; any escalation forces route `refer-to-committee`; wording of a final decision ("hereby approved", "final decision") is blocked (`output_blocked`); a model may only claim the escalation reasons `corpus_insufficient`, `conflicting_provisions`, `committee_discretion`.

Supported petition type: **attendance only** (`agents/policy.py`). re-evaluation, re-registration, medical-leave and grade-grievance are explicitly unsupported (`unsupported_petition_type`): no retrieval is attempted. Reasons: `docs/corpus_verification.md`.

Bounds (env): `MAX_RESEARCH_STEPS=8` LLM steps per agent, `MAX_TOOL_CALLS=10` per run, `MAX_RUN_SECONDS=120`, `MAX_VERIFY_RETRIES=2` (so at most 3 verifier attempts), `LLM_TIMEOUT_SECONDS`, `TOOL_TIMEOUT_SECONDS`. Step/tool-call exhaustion stops research and hands partial evidence on (the verifier escalates if it is insufficient); wall-clock exhaustion escalates `budget_exhausted`.

Failure matrix (implemented, tested with fakes): LLM error/timeout -> `llm_unavailable`; no LLM configured -> `llm_unavailable` with a clear message; invalid JSON/schema twice -> `invalid_agent_output`; unexpected exception in an agent -> `agent_error`; Chroma/embedding failure with no evidence -> `retrieval_unavailable`; verification still failing after retries -> `verification_failed`. All end as status `escalated` with `position: NO_DETERMINATION` and no citations. Only a failure of the graph machinery itself marks the run `failed`.

Recorded in `run_events` (visible in `GET /v1/runs/{id}`): `prompt_versions`, `agent_start/agent_end`, `llm_call` (agent, prompt id + sha, latency, tokens, model, ok/error), `tool_call` (tool, args, result clause ids/pages/scores, latency), `handoff`, `verification` (verified citations and failures per attempt), `escalation`. The final result also carries `prompt_versions`, `agent_stats` and token `usage`.

Not in Phase 3: retry/backoff, circuit breaker, fallback model, caching, rate limiting (Phase 4); prompt-injection and toxicity guardrails, evaluation metrics, cost in currency (Phase 5); tracing/metrics (Phase 6). `llm/client.py` is a minimal OpenAI-compatible HTTP client with a timeout; no LLM client existed before Phase 3.


## Phase 4 — reliability layer (`src/triage/reliability/`)
```
agent -> AgentContext.call_json -> ResilientLLM -+-> [primary]  breaker.allow? -> retry+backoff+jitter -> OpenAICompatClient -> provider
                                                 +-> [fallback] (optional, same pattern, own breaker)
                                                 +-> none available -> LLMError/CircuitOpen -> graph escalates: llm_unavailable, NO_DETERMINATION
API  -> rate limiter (Redis fixed window per client) -> 429 + Retry-After  |  worker -> metrics (Redis hash) <- API /metrics
retrieval -> CachedRetriever / CachedEmbedder (Redis; keys carry corpus fingerprint + embedding tag); get_chunk never cached
```
Decisions and trade-offs are in `docs/reliability.md`. Breaker and rate-limit state live in Redis so every worker/API replica sees the same state; the price is that Redis is now a
hard dependency of the LLM path (if Redis is down the queue is down anyway). Metrics are Redis hashes rather than per-process Prometheus clients because API and workers are separate
processes that must be aggregated; the API renders them at `/metrics`.

## Phase 5 — guardrails, evaluation, feedback, cost
* `guardrails/`: injection patterns, toxicity baseline, tool-argument validation, numeric-claim check; hooked into the graph (before triage), the tool box and the verifier (`docs/guardrails.md`).
* `evaluation/`: scenarios (`eval/scenarios.json`), scripted models, deterministic metrics, optional LLM judge, CLI, retrieval experiment, sampled auto-eval after a run finishes (`docs/evaluation.md`).
* `cost.py`, `db.py` (`feedback`, `run_evals` tables, `run_stats`), API endpoints for feedback/stats.

## Phase 6 — observability (`src/triage/observability/`, `observability/`)
```
api  --JSON logs, X-Correlation-ID, spans, /metrics-->   stdout | Jaeger (OTLP/HTTP :4318) | Prometheus :9090 -> Grafana :3000
worker --JSON logs, restored correlation id, child spans (traceparent passed as job arg), metrics into Redis
cAdvisor :8080 -> Prometheus (container CPU/memory)            all observability services are an opt-in compose profile
```
The run trace endpoint reconstructs a run from `run_events`, so debugging does not depend on the tracing stack being up. See `docs/observability.md`.

## Phase 7 — load-test topology
`locust` (container) -> `api` -> redis -> `worker xN` -> chroma + real embeddings; only the LLM is the `llm-stub` container. Orchestrator: `loadtest/benchmark.py`.
