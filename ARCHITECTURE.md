# Architecture

> Companion documents: `README.md` (setup), `PROJECT_STATUS.md` (what is verified), `KNOWN_LIMITATIONS.md`,
> `SECURITY_REVIEW.md`, `TESTING_REPORT.md`, `SYSTEM_TESTING_REPORT.md`, `LOAD_TEST_REPORT.md`, `DEMO_GUIDE.md`.
> Deeper per-topic notes live in `docs/` (retrieval design, guardrails, reliability, observability, runbook, SLOs).

## 1. What the system does

A student submits a **synthetic** academic petition. The system validates it, queues it, and three cooperating AI agents
triage it, retrieve the relevant university regulations and verify every citation. The result is a **recommendation** for a
human examiner. The AI never makes a final decision: the examiner records their own decision, stored separately.

## 2. Components

```
 Browser ──► web (nginx :8080) ──/api──► api (FastAPI :8000) ──► Redis (RQ queue, breaker, cache, metrics)
   React SPA                                   │                         │
                                               ▼                         ▼
                                       SQLite (WAL) ◄──────────── worker (RQ SimpleWorker)
                                       runs, events,                │  LangGraph: triage → research ⇄ verify → finalize
                                       decisions, documents         ├──► Chroma (vector index)  + BM25 (in-process)
                                                                    ├──► sentence-transformers (local embeddings)
 Streamlit ui (:8501) = fallback UI                                 └──► OpenAI-compatible LLM provider (HTTPS)
 Observability profile: Jaeger :16686 · Prometheus :9090 · Grafana :3000 · cAdvisor :8081
```

| Service | Image / code | Role |
|---|---|---|
| `web` | `frontend/` (React + Vite + TypeScript + Tailwind, built into nginx) | Student, Examiner and System portals. nginx serves the SPA and reverse-proxies `/api/*` to `api` (same origin, so no CORS). |
| `ui` | `ui/` (Streamlit) | Earlier UI, kept as a working fallback. |
| `api` | `src/triage/api` | Validation, quarantine, queueing, run/decision/document endpoints, stats, health, metrics. |
| `worker` | `src/triage/worker` | Runs the agent graph for each queued petition (scale with `--scale worker=N`). |
| `redis` | `redis:7-alpine` | RQ queue, LLM circuit breaker, rate-limit counters, retrieval/embedding cache, metrics. |
| `chroma` | `chromadb/chroma` | Vector index of the regulation chunks. |
| `ingest` | `src/triage/retrieval` | One-shot job: parse PDF → chunk → embed → upsert (idempotent). |

## 3. Request lifecycle

1. `POST /v1/petitions` – body size ≤ 64 KiB, rate limited, validated against the Pydantic contract. Invalid payloads get **HTTP 422 with
   field errors and are quarantined**; no run is created.
2. A `runs` row is created (`queued`) and an RQ job is enqueued with a timeout of *run budget + 60 s*.
3. A worker marks the run `running` and executes the agent graph. Every step is appended to `run_events`.
4. The run ends `completed` (a recommendation without escalation), `escalated` (a human must decide) or `failed` (infrastructure error).
5. The examiner opens the petition, reads the recommendation and evidence, and `POST`s a **separate** decision.

## 4. Agent workflow (LangGraph)

```
START → triage ──(unsafe / unsupported / ambiguous / inconsistent)──► finalize
          │ ok
          ▼
       research ──► verify ──(verification failed, retries left)──► research (with feedback hint)
                       │ determination or escalation
                       ▼
                    finalize → END
```

| Agent | Responsibility | Never does |
|---|---|---|
| **Triage** | Classify the petition, extract facts, detect contradictions (model **and** deterministic regex), flag unsupported types, produce a confidence. Input guardrails run first: injection / abuse text is escalated **without** being sent to the model. | Retrieve regulations or decide. |
| **Research** | LLM-driven loop choosing tools: `search_semantic`, `search_keyword`, `search_hybrid` (RRF fusion, prompt v2), `get_clause`, `get_neighbouring_clauses`, `get_petition_fields`, `finish`. Tool arguments are allow-listed and bounded; retrieved passages are scanned as untrusted text. | Cite or recommend. |
| **Verifier / Adjudicator** | Judge **only** the retrieved evidence. Every citation must name a retrieved evidence id and quote text that is a verbatim substring of the **re-read indexed chunk**; page, document and clause come from the index, not the model. Applies deterministic policy: output filter (no "approved/granted/final decision"), numeric-claim check, reserved-authority downgrade, and *no AI rejection inside the condonable band*. | Invent clauses or quotes; issue a final decision. |

Failure handling: any exception inside a node becomes an **escalation** (`llm_unavailable`, `invalid_agent_output`, `budget_exhausted`,
`retrieval_unavailable`, `agent_error`, …) – never a confident answer. Budgets bound steps, tool calls and wall-clock time.

### Escalation reasons
`committee_discretion`, `corpus_insufficient`, `conflicting_provisions`, `unsupported_petition_type`, `petition_inconsistent`,
`petition_ambiguous`, `verification_failed`, `budget_exhausted`, `invalid_agent_output`, `agent_error`, `llm_unavailable`,
`retrieval_unavailable`, `output_blocked`, `unsafe_input`.

## 5. RAG pipeline

`PDF → PyMuPDF per page → strip running headers/footers → skip contents pages → clause-aware chunks (one per printed item, e.g.
25OB10.0(4)) → topic tags → embed (local all-MiniLM-L6-v2) → Chroma upsert + manifest`. Idempotent: unchanged inputs embed nothing.
Retrieval: semantic (cosine), keyword (BM25), **hybrid** (reciprocal-rank fusion of both), exact clause lookup, neighbours.
`corpus/verified_passages.json` quotes are re-checked against the source page text **and** the index at every ingestion.
Citations carry `document`, `chapter`, `clause_id`, `page`, `quote`, `verified`. See `docs/retrieval_design.md`.

## 6. LLM integration (`src/triage/llm`, `src/triage/reliability`)

OpenAI-compatible `/chat/completions` over HTTPS; provider, model and key come only from environment variables. Per call: timeout,
classified errors, redacted provider messages. Wrapper: bounded exponential back-off with jitter, `Retry-After` honouring, 8 patient retries
for rate limits (within the run budget), a Redis circuit breaker, an optional fallback provider, and **proactive pacing from the provider's
`x-ratelimit-*` headers**. A note is appended to every system prompt that forbids native tool calls (some hosted models otherwise emit them
and the provider answers HTTP 400).

## 7. Data model (SQLite, WAL)

| Table | Purpose |
|---|---|
| `runs` | One row per petition: status, petition JSON, result JSON (the **AI recommendation**), error. |
| `run_events` | Append-only event log per run (agent start/end, tool calls, LLM calls, retries, guardrails, verification, escalation). |
| `examiner_decisions` | **Human** decisions, append-only, with a frozen snapshot of the AI route/position at decision time. |
| `documents` | Metadata of student-uploaded files (the bytes are on disk under `uploads/<run_id>/`, server-chosen names). |
| `quarantine` | Rejected (invalid) payloads. |
| `feedback`, `run_evals` | Reviewer ratings; optional LLM-judge scores. |
| `ingest_runs` | Manifest of every ingestion. |

## 8. API (FastAPI, `/docs` for the live schema)

| Method & path | Purpose |
|---|---|
| `POST /v1/petitions` | Submit (202) · 422 with field errors · 413 oversize · 429 rate limit · 503 queue down |
| `GET /v1/runs` | List with `status`, `student_ref`, `petition_type`, `limit`, `offset` filters |
| `GET /v1/runs/{id}` | Run, petition, AI result, events, human decisions, documents |
| `GET /v1/runs/{id}/trace` | Reconstructed agents, LLM calls, retrieval history, retries |
| `POST /v1/runs/{id}/examiner-decision` | Record a human decision (accept / reject / request more information) |
| `POST /v1/runs/{id}/documents` · `GET …/documents/{doc_id}` | Upload (PDF/PNG/JPEG, ≤ 2 MB, ≤ 3) · download as attachment |
| `POST /v1/runs/{id}/feedback`, `GET /v1/feedback` | Reviewer feedback |
| `GET /v1/stats`, `/v1/stats/agents`, `/v1/system`, `/v1/evaluation`, `/v1/corpus`, `/v1/quarantine` | Data for the dashboards |
| `GET /healthz`, `/readyz`, `/metrics` | Liveness, readiness (+ degradation reasons), Prometheus |

## 9. Frontend (`frontend/`)

React 18, Vite, TypeScript (strict), Tailwind with shadcn/ui-style components on Radix, Lucide icons, Recharts, React Router, TanStack Query.
Three portals behind a **demonstration role switch (not authentication)**:

* **Student** – overview, new-petition form (validation mirrors the server), document upload, petition history (by synthetic reference), status
  tracking, AI assessment with citations, human decision.
* **Examiner** – dashboard, filterable queue, petition review (petition, documents, recommendation, evidence, pipeline trace), decision form,
  decision history.
* **System** – service/queue/provider/retrieval health, petition and agent statistics, evaluation reports. All numbers come from the API.

## 10. Trust boundaries

Petition text and retrieved passages are untrusted data. The model is never given tools beyond the allow-listed retrieval functions; it cannot
write to the database. Uploaded documents are stored, never parsed or shown to a model. There is **no authentication**: see `SECURITY_REVIEW.md`.
