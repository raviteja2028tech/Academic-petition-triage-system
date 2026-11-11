# SPEC.md — Academic Regulation and Student Petition Triage Service

Mini Project 15 · UE24AM342AA5 ML System Design & AgentOps · Dept of CSE (AI & ML), PESU
Source of truth: `MiniProject_15_Academic_Petition_Triage.pdf` (5 pages, fully read, text layer present).
Status of this document: **the original plan, kept as written (the matrix and phase plan below are not rewritten); the implementation status is in the block below and in `PROJECT_STATUS.md`.**

> **Implementation status (2026-10-28, after Phases 4-8):** all phases have code and tests; the authoritative, evidence-backed state (exact test counts, Docker runs, benchmark numbers, what was NOT done) is `PROJECT_STATUS.md` and `docs/final_report.md`. Requirement status below uses: DONE+TESTED / IMPLEMENTED (not fully verified) / PARTIAL / BLOCKED.
>
> | Req | Status | Note |
> |-----|--------|------|
> | F1, F2, D1 | DONE+TESTED | API contract, validation, quarantine |
> | F3, F4, F5, F6, F7, A1, A2, A3 | IMPLEMENTED (not fully verified) | agents/verification/escalation tested with scripted models + an LLM stub; **no real LLM run**; §4.1 case NOT claimed to pass |
> | F8, D5 | DONE+TESTED (Jaeger/Prometheus/Grafana/cAdvisor verified through their HTTP APIs; dashboards not viewed in a browser) | JSON logs, correlation id, OTel->Jaeger, Prometheus, Grafana, cAdvisor |
> | A4, A8 | DONE+TESTED (UI submit->result checked in a headless browser, run page only) | async runs, Streamlit client |
> | A5 | DONE+TESTED (fakes; stub fault injection in Docker) | timeouts, retry+backoff+jitter, Redis breaker, fallback, degradation |
> | A6 | DONE+TESTED | per-agent counts/latency/tool calls/retries/outcomes, e2e latency, error rate |
> | A7 | PARTIAL; measured 1/2/3 workers (see `docs/LOAD_TEST.md`) | scaling measured with the LLM stub; see report for what did/did not scale |
> | L1, D2 | DONE+TESTED | ingest/selective re-embed/manifest |
> | L2 | PARTIAL | versioned prompts + recorded per run; second variant (research_v2) exists but the comparison needs a real LLM: NOT RUN |
> | L3 | IMPLEMENTED (scripted mode run; real mode NOT RUN) | 28 scenarios, CLI, metrics; TruLens not used (own deterministic metrics + optional LLM judge) |
> | L4 | DONE+TESTED (heuristic) | injection/toxicity/tool/arg/schema/output guardrails; limits in `docs/guardrails.md` |
> | L5, L6 | DONE+TESTED | token + estimated cost per call/run/100 runs; feedback endpoint + stats; sampled auto-eval implemented with fake judge only |
> | D3 | DONE+TESTED (stack started with Docker); clean-clone start NOT tested | compose stack, health checks |
> | D4 | DONE (open question A-3 on naming the embedding model in `.env.example`) | |
> | D6 | PARTIAL | SLO frozen before measurement; nominal-load (S4/S5) and cache runs NOT measured; S2 missed at >=4 users |
> | D7 | IMPLEMENTED+unit-tested | rate limit + caches; effect on p95/cost NOT measured |
> | D8 | DONE (scenario A exercised in Docker; B not) | runbook, incident log (genuine entries only) |
>
> Corpus: VTU B.E./B.Tech. Regulations 2025; difficult case `PARTIALLY_VERIFIED` (`docs/corpus_verification.md`). Findings that change the plan: condonation authority is the Vice-Chancellor (not a committee); examination bye-laws not supplied; re-evaluation regulations absent from the supplied file. Open questions A-1..A-6 remain.

---

## 0. Findings from reading the PDF

| # | Finding | Handling |
|---|---------|----------|
| 0.1 | The PDF lists **30** requirements (F1–F8, A1–A8, L1–L6, D1–D8) but §10 says "Completing all **22** requirements is not expected". The number does not match. | Treat all 30 as the list. Ask the course staff at Evaluation 1 which 22 (if any) are meant. Until answered, plan all 30 and prioritise (§2.2). |
| 0.2 | The PDF refers to `00_GLOSSARY.pdf`. It is **not in the folder**. | Not read; nothing was invented from it. Get it from the course page. Terms are used here in their standard meaning. |
| 0.3 | "Team size 2–3", "Component: Jackfruit (Level 3), 10 marks"; marking grid totals 40 (scaled to 8) over: problem/architecture (10), presentation/teamwork (10), engineering judgement (10), report/code/docs (10). | Marks reward **prioritisation and judgement**, not feature count. |
| 0.4 | **Zero-marks rule (§10):** if the system does not start and serve a valid request at the demo, the project gets zero. | Working end-to-end path by **end of week 2**; reliability of `docker compose up` outranks every enhancement. |
| 0.5 | Deliverables: **Evaluation 1** (one week before presentation) = corpus confirmation + project plan; **Evaluation 2** = report + final GitHub repo + live demo + viva. | Evaluation 1 package is defined under Phase 0 (§6) and §8. |
| 0.6 | At Evaluation 1 we must "show the passages in your corpus that the §4.1 case depends on, and the values you will test with". | Corpus selection/verification is the **first** task and the critical-path blocker (§8). |
| 0.7 | D4: "No credentials, endpoints or **model identifiers** anywhere in the repository." | Model names (LLM *and* embedding model) and prices live only in `.env` (gitignored). `.env.example` carries placeholders, not real identifiers. See ambiguity A-3. |
| 0.8 | F7 says "escalate to a human instead of answering" but F6 lists only three routes. | See ambiguity A-1 for the resolution. |

---

## 1. Scope in one paragraph

A multi-agent service that accepts a **synthetic** student petition over REST, validates it at the boundary (quarantining rejects), runs it asynchronously through a LangGraph agent system that *chooses* to call retrieval tools over one Indian university's regulations + examination bye-laws, **verifies every citation against retrieved text**, and returns an **eligibility position + routed recommendation** (`grant-under-provision` / `refer-to-committee` / `reject` with cited clause) or **escalates to a human**. The system never makes the final decision; an examination officer does. Everything runs under `docker compose up` with metrics, tracing, logs, load test, evaluation, runbook and incident log.

Out of scope (PDF §13): model training, cloud deployment, real student records.

---

## 2. Requirement classification

### 2.1 Mandatory vs optional

The PDF marks **no individual requirement as optional**; it says completing everything is not expected. We therefore plan all 30 and classify by risk:

* **Tier 1 – Survival (zero-mark risk, must be perfect):** F1, F2, F3, F4, F5, F6, F7, A4, A8, D1, D3, D4, plus demo items 1, 2, 10.
* **Tier 2 – Core agent/LLMOps marks:** A1, A2, A3, A5, L1, L3, L4, D2, D5, F8, demo items 3–8.
* **Tier 3 – Measured-experiment marks:** A6, A7, L2, L5, L6, D6, D7, D8, demo item 9.
* **Optional enhancements (only after Tier 1–3 are green):** Grafana per-container panels beyond the minimum, Tempo instead of Jaeger, ML-based toxicity model (lexicon baseline is the plan), second corpus document set, Streamlit animations/polish, callback (webhook) delivery in addition to polling, TruLens dashboard (custom RAG-triad evaluator is the baseline).

### 2.2 Requirements needing clarification (ask at Evaluation 1)

| ID | Question | Proposed resolution if unanswered |
|----|----------|-----------------------------------|
| A-1 | F6 has three routes; F7 says "escalate instead of answering". Is escalation a fourth outcome? | Treat escalation as an **overlay**: result has `route` ∈ the three values **plus** an `escalation` object (`required: true/false`, `reason` enum). Committee-reserved discretion → `route=refer-to-committee, escalation.required=true`. Corpus gap / unsupported type / failed verification → `route=refer-to-committee`, `escalation.required=true`, **`position=NO_DETERMINATION`**, no citation fabricated. API field `status=escalated`. |
| A-2 | A2: is "two agents" satisfied by two LangGraph sub-graphs in one worker process, or must they be separate processes/containers? The PDF says "two prompts in one process are not two agents". | Build **three agents** as separate LangGraph sub-graphs with (a) separate state schemas, (b) separate tool allow-lists, (c) separate step/tool/time budgets, (d) separate prompts+prompt versions, (e) a typed hand-off contract, (f) separate failure handling and per-agent metrics/spans. Stay in one worker process (simplicity, latency). Document the choice and confirm with staff; fallback if rejected: run the Researcher as its own `agent-researcher` service called over HTTP (design allows this because the hand-off is already a serialised contract). |
| A-3 | D4 forbids "model identifiers" in the repo, yet the embedding model name must be known. | Both LLM and embedding model names are read from env (`LLM_MODEL`, `EMBED_MODEL`); only `.env.example` documents *variable names* with placeholder values like `<set-me>`. The README says which model the team used. Confirm with staff whether naming the model in the README/report is acceptable. |
| A-4 | A6 "task success rate" — what is success? | Define: run reaches a terminal state `completed` or `escalated` **with verification passed or a valid escalation reason** (i.e. no crash, timeout or unverified answer). `failed`/`degraded-unverified` count as failure. Document in `docs/metrics.md`. |
| A-5 | A7/D6 stub: should the stub replace *only* the LLM? | Yes. Embeddings/retrieval stay real so the test measures our system. Stub service `llm-stub` (OpenAI-compatible, fixed JSON responses, configurable delay). |
| A-6 | Is a custom evaluator acceptable as "TruLens or equivalent"? | Plan: custom RAG-triad evaluator (LLM-as-judge + deterministic checks) as baseline because TruLens' dependency weight/API churn is a risk. Attempt TruLens only if time remains. PDF text explicitly allows "equivalent". |

### 2.3 Requirements dependent on the corpus

F3 (classification categories actually supported), F4, F5, F6, F7, L1, L3, D2, §4.1 demo (item 10), evaluation scenarios S01–S14, and the "unsupported request" demo (item 5). **Nothing about clause numbers, percentages or ranges is assumed in this document; every `⟦CORPUS⟧` marker is filled only after verification (§8).**

---

## 3. Requirement traceability matrix

Phases refer to §6. Priority: C = Critical, H = High, M = Medium.
Module names refer to the structure in §5.

### 3.1 Functional (F)

| ID | Meaning (simple) | Planned implementation | Files / services | How tested | Acceptance criteria | Pri | Ph |
|----|------------------|------------------------|------------------|-----------|---------------------|-----|----|
| F1 | Accept a petition via a documented REST API with a published data contract | `POST /v1/petitions` (JSON) → `202 {run_id}`; OpenAPI auto-published at `/docs`; contract in `docs/data_contract.md` generated from Pydantic models | `api`, `src/triage/contracts.py`, `docs/data_contract.md` | pytest API tests; contract-doc diff check against `/openapi.json`; curl in README | Valid body → 202 + run_id within 1s; docs reachable; every field documented with type/range/enum | C | 1 |
| F2 | Validate schema, range, category, cross-field at the door; quarantine bad ones | Pydantic v2 models + cross-field validators in `validation.py`; failures → `422` with field-level errors **and** a row in `quarantine` table; no queue job created | `api`, `validation.py`, `db.py` (quarantine) | pytest: S15–S18 (+ property-style fuzz of ranges); assert queue length unchanged, no `runs` row | 100% of malformed samples rejected; each quarantine row stores payload hash, errors[{field,rule,msg}], timestamp, client_id; zero runs created | C | 1 |
| F3 | Classify petition type (attendance, re-evaluation, re-registration, medical leave, grade grievance) and extract entities | **Triage Agent**: deterministic hint from structured `petition_type` + LLM structured-output classification of `petition_text`; extract course, semester, attendance %, reason category, documentation; flag mismatch between declared type and text | `agents/triage_agent.py`, prompt `triage_v*.yaml` | Eval scenarios S01–S14, S22–S23; unit tests with stub LLM; accuracy on type ≥ target set in `docs/eval_plan` | Output validates against `TriageResult` schema; type mismatch yields escalation or clarification flag, not silent override | C | 3 |
| F4 | Retrieve base provision AND any provision that modifies it (condonation) | **Research Agent** tool loop: hop 1 base rule → look for modifiers (`condonation`, `shortfall`, `exception`, `discretion`) → hop 2 query *derived from hop-1 text* (e.g. clause titles/keywords found) → optional neighbour/cross-ref expansion | `agents/research_agent.py`, `agents/tools.py`, `retrieval/search.py` | S01 must retrieve both base and condonation clause IDs (`⟦CORPUS⟧`); retrieval recall@k on gold clause IDs across eval set | S01 evidence set ⊇ {base clause, condonation clause}; recall of gold clauses ≥ target (set after baseline) | C | 3 |
| F5 | Eligibility position grounded in retrieved text with chapter+clause citations | **Verifier/Adjudicator Agent** composes position from *verified* evidence only; citation = `{doc, chapter, clause_id, page, quote}`; structured output schema | `agents/verifier_agent.py`, `contracts.py (Citation)` | A3 test suite: every citation resolves; S24 fabricated-citation injection is caught | 100% of returned citations resolve to retrieved chunk text (substring match after normalisation); no citation → no confident position | C | 3 |
| F6 | Route to grant-under-provision / refer-to-committee / reject-with-cited-clause, with basis | Routing enum in contract; rule table in verifier prompt + deterministic post-check (e.g. `reject` requires ≥1 verified clause citation; `grant` requires a verified provision that *permits* grant and no committee-reserved wording) | `verifier_agent.py`, `guardrails/output_filter.py` | Eval expected-route accuracy per scenario; unit tests on post-check | Route ∈ enum always; `basis` non-empty; `reject` without citation is impossible (output filter blocks) | C | 3 |
| F7 | Escalate rather than answer when provisions conflict, committee discretion reserved, or type outside corpus | Escalation reasons enum: `corpus_insufficient`, `conflicting_provisions`, `committee_discretion`, `unsupported_petition_type`, `verification_failed`, `system_degraded`, `guardrail_blocked`. Conflict detection by verifier (LLM + clause-pair prompt); discretion detection by lexical triggers + LLM; unsupported type by retrieval-score floor + type allow-list | `verifier_agent.py`, `graph.py` | S05, S09, S11–S14, S24, S25; "never answers" assertion tests | For every escalation scenario: `escalation.required=true`, correct reason, no determination text, no fabricated citation | C | 3 |
| F8 | Health, metrics, structured logs across the pipeline | `/healthz` (liveness), `/readyz` (Redis, DB, Chroma, LLM-breaker state), `/metrics` on api + worker; JSON logs with correlation id | `api`, `worker`, `observability/*` | pytest for health; Prometheus targets all UP; log schema test | Health endpoints reflect real dependency state; each service logs JSON incl. `run_id`, `correlation_id`, `service`, `step` | H | 1 (basic) / 6 (full) |

### 3.2 Agent system (A)

| ID | Meaning | Planned implementation | Files / services | Test | Acceptance | Pri | Ph |
|----|---------|------------------------|------------------|------|-----------|-----|----|
| A1 | LangGraph reasoning; retrieval is a **tool the agent chooses**; ≥3 tools; bounded loop (steps, tool calls, wall-clock) | LangGraph graph; Research Agent is a ReAct-style node-loop where the LLM emits tool calls. Tools: `search_corpus(query, strategy, top_k, filters)`, `get_clause(clause_id)`, `get_petition_fields()`, `get_neighbouring_clauses(clause_id)`. `Budget` object: `max_steps`, `max_tool_calls`, `max_seconds` (from env) enforced in every loop iteration | `agents/tools.py`, `agents/budget.py`, `agents/research_agent.py` | Unit: scripted LLM that loops forever → terminates at each limit with `budget_exhausted` escalation; assert agent *can* answer without calling search (it chooses) | Each limit independently triggers termination; trace shows which tool the agent chose; ≥3 tools registered | C | 3 |
| A2 | ≥2 distinct agents, defined hand-off; document topology and mid-run failure | 3 agents (Triage → Research → Verifier/Adjudicator), typed hand-off objects (`TriageResult` → `EvidenceBundle` → `Determination`). Topology doc + failure matrix in `docs/architecture.md` | `agents/*`, `docs/architecture.md` | Fault-injection tests: raise in each agent; assert run ends `failed`/`escalated(system_degraded)`, never confident | Failure matrix covers each agent × {exception, timeout, bad output}; behaviour as documented | C | 3 |
| A3 | Verify every answer vs retrieved passages; unverified answer never returned; retry different strategy or escalate | Verifier performs (1) deterministic citation check: clause_id ∈ retrieved set and quoted span ⊆ chunk text; (2) LLM entailment check claim→passage; on fail: **retry** with a different strategy (dense → hybrid/keyword → clause-id lookup → section-filtered), max `MAX_VERIFY_RETRIES` (2); then escalate `verification_failed` | `verifier_agent.py`, `retrieval/search.py` | S24: stub LLM forced to emit fabricated clause → caught → retry → escalation or corrected; unit tests of substring matcher | Zero unverified citations ever in `completed` results (asserted by test over entire eval run) | C | 3 |
| A4 | FastAPI, async runs: immediate run id, poll status, queue between submission and execution; justify | `POST` returns 202 + `run_id`; `GET /v1/runs/{id}` polls; **Redis + RQ** queue; worker pulls jobs. Justification (in docs): runs last tens of seconds, HTTP timeouts/proxies, burst absorption, independent scaling of workers, retry/isolation. Polling chosen over callbacks (simpler, works behind NAT, client-driven); optional `callback_url` is a stretch | `api`, `worker/tasks.py`, Redis | Integration test: submit → poll until terminal; submission latency < 1s while run takes ≫ 1s with stub delay | 202 returned before any model call; state machine `queued→running→completed|escalated|failed`; job survives API restart | C | 1 |
| A5 | Timeouts on every model/tool call; bounded retry w/ exponential backoff; circuit breaker; graceful degradation; no confident answer from incomplete run | `llm/client.py` wraps every call: per-call timeout, retries (max 3, backoff `base·2^n` + jitter, only on retryable errors); `llm/breaker.py` Redis-backed (shared across workers): closed/open/half-open, threshold N failures in window, cooldown. Tool calls wrapped with timeouts. **Fallback path:** primary model → secondary model (env) → *retrieval-only degraded mode* (returns retrieved passages + `escalation.reason=system_degraded`, no position). Incomplete run ⇒ status `failed` or `escalated`, never `completed` | `llm/client.py`, `llm/breaker.py`, `llm/retry.py`, `agents/graph.py` | Unit: fake provider failing → backoff timings; breaker state transitions; chaos test via `llm-stub` fail-mode toggle | Demo item 8 reproducible on request: breaker opens after N failures, subsequent calls fail fast (no provider call), degraded result returned and labelled, breaker half-opens and closes on recovery | C | 4 |
| A6 | Per-agent task success rate, steps & tool calls per run, end-to-end & per-step latency, retry rate, container uptime on a dashboard | Prometheus metrics labelled by `agent`: `agent_runs_total{outcome}`, `agent_steps`, `agent_tool_calls`, `step_latency_seconds`, `run_latency_seconds`, `llm_retries_total`; uptime from cAdvisor / `process_start_time_seconds`. Dashboards: Grafana (ops) + Streamlit "System" page reading `/v1/stats` | `observability/metrics.py`, `monitoring/grafana/*`, `ui/pages/3_System.py` | Run 20 eval runs, check every panel non-empty and matches DB counts | All six quantities visible per agent; numbers reconcile with `run_events` table | H | 6 |
| A7 | `docker compose up --scale <worker>=3` works; measure throughput & p95 effect with the stub; identify bottleneck if no gain | Worker service has no fixed `container_name`/host port; Prometheus uses DNS service discovery for replicas; Locust runs at scale 1,2,3 with identical load | `docker-compose.yml`, `monitoring/prometheus.yml`, `loadtest/` | Load test matrix (scale 1/2/3 × concurrency steps); results table in `docs/load_test.md` | Scale-3 starts clean and all replicas process jobs; report shows RPS/p95 per scale and named bottleneck (e.g. SQLite write lock, Chroma, CPU embedding, stub concurrency) | H | 7 |
| A8 | Simple web client: submit, get result, show recommendation + citations + escalation path | Streamlit app calling FastAPI only (no business logic) — see §4 | `ui/` | Manual + Playwright-less smoke test: API-driven; UI renders fields from fixture | Submit → progress → result with route, basis, citations, escalation reason | C | 1 (minimal) / 6 (polish) |

### 3.3 LLMOps (L)

| ID | Meaning | Planned implementation | Files / services | Test | Acceptance | Pri | Ph |
|----|---------|------------------------|------------------|------|-----------|-----|----|
| L1 | LangChain retrieval + FAISS/Chroma; document chunking & embedding; re-embed without rebuilding all | **Chroma** (server container) via LangChain `Chroma` wrapper. Structure-aware chunking: one chunk per clause with breadcrumb prefix (see §8.3). Stable chunk id = hash(doc_id, clause_id, text). Metadata: `embed_model_tag`, `doc_version`. Re-embed = `ingest --reembed --model-tag X` re-computes only chunks whose tag/hash changed (upsert) | `retrieval/*`, `docs/retrieval_design.md` | Test: change one clause → only 1 chunk re-embedded (count assertions); change model tag → only mismatching chunks | Documented strategy explaining §3 difficulty; partial re-embed demonstrated with counts | C | 2 |
| L2 | Versioned prompts; version recorded in each response; compare ≥2 variants on same eval set | Prompts as YAML files `prompts/<agent>_v<N>.yaml` with `version`, `template`, `sha256`; active versions selected by env; recorded in `runs` and every `run_events` row and API response. `eval --prompt-set vA|vB` writes comparison table | `llm/prompts.py`, `prompts/`, `eval/` | Unit: response carries versions; eval comparison script | Report states which variant won, on which metric, by how much (e.g. "v2 +X pp groundedness") | H | 5 |
| L3 | Fixed eval set ≥20 scenarios w/ expected outcome and supporting passage incl. §4.1; batch CLI; TruLens or equivalent; report groundedness, context relevance, faithfulness, hallucination rate with computation; one deliberate change, all four before/after | `eval/scenarios.yaml` (24, §9); `python -m triage.eval.run_eval --set eval/scenarios.yaml --out eval/results/<ts>.json`; custom RAG-triad (§9.3); before/after experiment (§9.4) | `eval/`, `src/triage/eval/` | CLI exit code + JSON/markdown report; determinism seeded where possible | ≥20 scenarios, each with expected route/escalation + gold clause IDs; four metrics reported before and after one change with method text | C | 5 |
| L4 | Prompt-injection defence on every free-text field reaching a model; output filtering so system cannot issue unauthorised determination; toxicity on input & output | `guardrails/injection.py`: layered — (1) normalisation + heuristic detector (instruction-override patterns), (2) delimiting/quoting untrusted text as data in prompts with fixed system rules, (3) **tool-argument validation** so injected text can't call tools out of allow-list or change `clause_id` outside corpus, (4) optional LLM classifier. `guardrails/toxicity.py` lexicon baseline on input+output. `guardrails/output_filter.py`: schema-enforce output, route enum only, block phrases implying a final decision ("approved", "final decision", "I hereby…") and require "recommendation/position" wording; no tool in the toolset can write a decision | `guardrails/*` | S19–S21 + unit tests; red-team list of ≥15 injection strings | Injection scenarios never change route/tool behaviour; flagged runs escalate `guardrail_blocked`; toxic input quarantined or escalated; output filter blocks forced "final decision" text | C | 5 |
| L5 | Record prompt/completion tokens & cost at call time, per step and per run; cost per 100 runs; largest driver | `llm/client.py` records usage from provider response (fallback: tokenizer estimate flagged `estimated=true`) into `run_events`; `cost.py` multiplies by price table from env (free tier ⇒ report both $0 actual and *shadow cost* at reference prices) | `llm/cost.py`, `db.py` | Unit: cost arithmetic; eval run aggregates; check sum(step)=run | `GET /v1/runs/{id}/trace` shows per-step tokens & cost; report has cost/100 runs and top driver by step/agent | H | 5 |
| L6 | Feedback endpoint (satisfactory + reason) persisted & aggregated; auto-score a sample of live runs; chart quality over time | `POST /v1/runs/{id}/feedback`; table `feedback`; `GET /v1/stats/feedback`. Sampler: `EVAL_SAMPLE_RATE` of completed runs enqueued to low-priority `eval` queue; judge computes metrics; stored in `run_scores`; Streamlit time-series chart + Prometheus gauge | `api`, `worker/tasks.py (score_run)`, `ui/pages/3_System.py` | pytest feedback persistence; run 20 live runs and confirm ~sample scored | Feedback persisted with reason, aggregated rate shown; quality chart over time shows scored runs | M | 5 |

### 3.4 Platform & deployment (D)

| ID | Meaning | Planned implementation | Files / services | Test | Acceptance | Pri | Ph |
|----|---------|------------------------|------------------|------|-----------|-----|----|
| D1 | Data contract for every external interface; validation before any agent; quarantine; malformed ≠ run | Contracts for: petition request, run status/result, feedback, health, error. Pydantic = single source; `docs/data_contract.md` generated; validation happens in API handler *before* enqueue | `contracts.py`, `validation.py`, `docs/data_contract.md` | Same as F2 + assert enqueue not called (mock) | Contract doc matches code (CI check); malformed → 422 + quarantine, zero runs | C | 1 |
| D2 | Idempotent corpus pipeline (read, parse, chunk, embed, index) via CLI; record freshness; expose as metrics | `python -m triage.retrieval.ingest [--reembed]`; content hashes per document and chunk; run twice ⇒ second run does zero embeds; writes `index_manifest` (built_at, doc names+versions+sha256, chunk count, embed model tag, duration, chunks/sec). Metrics: `corpus_index_built_timestamp`, `corpus_chunks_total`, `ingest_chunks_per_second`, `ingest_last_duration_seconds` pushed via `/metrics` of api (reads manifest) | `retrieval/ingest.py`, `index_manifest` table | Test: idempotency (2nd run no-op); metrics present | Re-run is no-op; manifest + metrics visible; `docker compose run ingest` works | H | 2 |
| D3 | ≥4 services, one `docker compose up` from clean clone, deps + health checks, nothing outside containers; justify boundaries | Services listed in §5.5 (≥8). `depends_on: condition: service_healthy` / `service_completed_successfully`; healthchecks on all long-running services | `docker-compose.yml`, `docker/*` | Fresh clone in a temp dir on a clean Docker state; CI-style script `scripts/clean_clone_test.sh` | Works on a clean clone; all services healthy within documented time; README includes boundary justification table | C | 1 (then re-verified each phase and 8) |
| D4 | No credentials/endpoints/model ids in repo; env injected; `.env.example` | `pydantic-settings` reading env; compose `env_file: .env`; `.env` gitignored; secret scan (gitleaks or grep script) in test; `.env.example` placeholders only | `config.py`, `.env.example`, `.gitignore` | `scripts/check_no_secrets.sh` (greps for key patterns, URLs, model names) | Scan clean; app fails fast with clear message when required vars are missing | C | 1 |
| D5 | Structured logs, correlation ID everywhere, OTel → Jaeger/Tempo, Prometheus scraping every service, Grafana (p50/p95, error rate, throughput, availability, per-container resources); full run reconstructable from run id | `structlog` JSON; `X-Correlation-ID` accepted/generated, stored as `correlation_id`, propagated in job meta and OTel baggage; OTel SDK + OTLP → **Jaeger**; trace context injected into the RQ job so API span and worker spans join one trace; append-only `run_events` (tool call, query, passage ids+scores, prompt version, step latency, tokens, cost, verification outcome); `GET /v1/runs/{id}/trace` reconstructs; Grafana provisioned dashboards; cAdvisor for per-container resources | `observability/*`, `monitoring/*`, `db.py` | Run one request; assert trace has all spans; compare `/trace` JSON to Jaeger; Prometheus targets UP | Demo item 3: from a `run_id` show every item listed; one trace id visible in Jaeger spanning api→queue→worker→agents→tools | H | 6 |
| D6 | Declare p95 SLO **before** measuring; measure submission→final result; Locust with LLM stub; RPS/p50/p95 vs target; concurrency where it fails and which component | `docs/SLO.md` committed (git timestamp proves ordering) *before* first load run; Locust user: submit → poll until terminal → record total time as custom event; stub with configurable delay (realistic, e.g. matching free-tier model latency, set in docs) | `docs/SLO.md`, `loadtest/locustfile.py`, `stub_llm/` | Load runs at stepped concurrency; Prometheus/Grafana + Locust CSV | SLO file predates results (commit order); report: RPS, p50, p95 vs target, met/not met, breaking concurrency, responsible component | H | 7 |
| D7 | Caching (justified) + per-client rate limiting; measure effect on p95 & cost/run | Redis caches: embedding cache (key=hash(model_tag,text)), retrieval cache (key=hash(query,strategy,corpus_version)), whole-run cache (key=hash(normalised petition,corpus_version,prompt versions)) with TTL; justify each. Rate limit: Redis token bucket per `X-API-Key`/client id → `429` + `Retry-After`; also per-client daily run budget | `api/ratelimit.py`, `cache.py` | Unit: limiter; load test with cache on/off; same-client loop script | 429 returned on loop; measured p95 and cost/run with cache on vs off tabulated | H | 4 |
| D8 | Runbook for two likely failure modes (symptom, confirmation, recovery) + incident log with ≥1 genuine entry from a real dev failure | `docs/runbook.md`: (1) LLM provider unavailable/rate-limited (breaker open), (2) queue backlog / worker down (also candidates: stale/empty index). `docs/incident_log.md` filled **only with real incidents as they occur** — start logging from day 1 | `docs/` | Execute each runbook once on a deliberately broken system and confirm recovery steps work | Both runbooks tested; incident log has ≥1 true entry (date, symptom, root cause, fix, prevention) | M | 8 (log from Phase 1) |

---

## 4. Architecture

### 4.1 Selected stack and justification

| Concern | Choice | Why (and what was rejected) |
|---------|--------|-----------------------------|
| UI | **Streamlit** (calls API only) | Fast to build, looks professional with a little CSS; business logic stays in FastAPI. Rejected: React (time cost). |
| API | **FastAPI** + Pydantic v2 | Auto OpenAPI = published contract; async; required by A4. |
| Agent orchestration | **LangGraph** | Required option; explicit graph = easy to explain in viva; bounded loops. CrewAI rejected (less control over budgets/traces). |
| RAG | **LangChain** retriever wrapper over **Chroma** | Chroma supports upsert/delete by id+metadata ⇒ selective re-embedding (L1). FAISS rejected: needs hand-built id/metadata store and full rebuild for partial updates. Chroma runs as a **server container** (shared by scaled workers, avoids SQLite file locking from many processes). |
| Embeddings | local `sentence-transformers` (small CPU model, name from env), baked into the worker image at build time | Free, offline demo, no API cost (PDF §12). |
| Keyword search | BM25 (`rank_bm25`) over chunk text, loaded in worker | Gives the "different retrieval strategy" for A3 retry; cheap. |
| Queue | **Redis + RQ** | Simplest queue that satisfies A4 and scales via `--scale`. Celery/Arq rejected as heavier/less familiar. |
| State | **SQLite** (WAL mode, volume shared by api+workers) for runs, run_events, quarantine, feedback, scores, manifest. Redis for queue, cache, rate-limit, breaker. | Zero extra service. **Known risk:** write contention under 3+ workers — a likely D6/A7 bottleneck candidate, to be measured and reported honestly. Upgrade path: Postgres service. |
| LLM access | Own `LLMClient` interface over an **OpenAI-compatible HTTP API** (works for Groq/Gemini-compat/OpenRouter free tiers, Ollama, and our stub) via env `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_FALLBACK_MODEL` | Provider switch by config only (PDF §12). |
| Metrics | `prometheus-client` → **Prometheus** → **Grafana**; **cAdvisor** for per-container CPU/mem/uptime | D5/A6. |
| Tracing | **OpenTelemetry** → **Jaeger** (all-in-one, OTLP) | Single container, simplest. Tempo rejected (needs Grafana wiring). |
| Logs | `structlog` JSON to stdout (read via `docker compose logs`) | No Loki — avoid extra service. |
| Tests / load | `pytest`, `Locust`, stub LLM service | PDF D6. |
| Eval | Custom RAG-triad evaluator (judge via LLM client) | See A-6. |
| Toxicity | Lexicon baseline (small, offline) behind an interface; ML detector optional | Avoids a heavy model; honest limitation documented. |

Avoided deliberately: Kubernetes, microservice-per-agent, paid APIs, Postgres/Kafka, model training.

### 4.2 Component diagram (deployment boundaries marked)

```
 Browser ──► [ui: Streamlit] ──HTTP──► [api: FastAPI] ──enqueue──► [redis] ◄──pull── [worker ×N]
                                         │   │  ▲                     ▲                │  │  │
                                         │   │  └─ rate limit/cache ──┘                │  │  └─► [llm provider | llm-stub]
                                         │   └───────► SQLite volume (runs, events, quarantine, feedback) ◄─┘  │
                                         │                                                                     └─► [chroma] (vectors)
                                         ▼
          [prometheus] ◄─scrape─ api, worker×N (DNS SD), chroma?, cadvisor, redis-exporter?
          [grafana] ◄─ prometheus          [jaeger] ◄─ OTLP ─ api, worker×N
          [ingest] one-shot job: PDFs → parse → chunk → embed → chroma (+manifest)
```

### 4.3 Services and why each boundary exists (D3)

| Service | Purpose | Boundary justification |
|---------|---------|------------------------|
| `ui` | Streamlit client | **Independent release** (UI changes without touching the API); failure isolation (UI crash doesn't stop runs). |
| `api` | REST, validation, quarantine, rate-limit, status, feedback, stats | **Resource profile**: light, I/O-bound image (no torch); must respond < 1s while workers are busy. |
| `worker` (scalable) | Runs agents, tools, retrieval, embeddings | **Scaling + resource profile**: CPU/RAM heavy (sentence-transformers); scaled horizontally (`--scale worker=3`); a crash loses only its job (retried/flagged). |
| `redis` | Queue, caches, rate limiter, breaker state | **Failure isolation / shared state** across scaled workers. |
| `chroma` | Vector store server | **Scaling**: shared by all workers without file-lock issues; independent persistence volume. |
| `ingest` (one-shot, `service_completed_successfully` gate) | Builds/updates index idempotently on `up` | **Independent release & lifecycle**: runs to completion, not a long-lived process; also re-invocable via `docker compose run`. |
| `llm-stub` (profile `loadtest`) | Fixed responses after delay | Required for D6; keeps the system under test separate from provider rate limits. |
| `prometheus`, `grafana`, `cadvisor`, `jaeger` | Observability | **Failure isolation**: observability outage must not affect serving. |

Total ≥ 8 long-running services (requirement is ≥4).

### 4.4 Data flow and run state machine

`POST /v1/petitions` → validate (F2/D1) → [fail: 422 + quarantine row, stop] → input guardrails (injection/toxicity) → create `runs` row (`queued`) → whole-run cache check (hit ⇒ copy result, `cache_hit=true`) → enqueue RQ job(correlation_id, traceparent) → `202 {run_id, status_url}`.
Worker: `queued → running → {completed | escalated | failed}` (+`degraded=true` flag). Client polls `GET /v1/runs/{id}`.

### 4.5 API surface (published in `docs/data_contract.md` + `/docs`)

| Method & path | Purpose |
|---------------|---------|
| `POST /v1/petitions` | Submit (202 / 422 / 429) |
| `GET /v1/runs/{run_id}` | Status + result when terminal |
| `GET /v1/runs/{run_id}/trace` | Full reconstruction (events, tool calls, queries, passages, prompt versions, per-step latency/tokens/cost, verification) |
| `POST /v1/runs/{run_id}/feedback` | Satisfactory flag + reason |
| `GET /v1/runs` | Recent runs list (dashboard) |
| `GET /v1/stats` | Aggregates (success rate, steps, latency, retry rate, cost, feedback, quality over time) |
| `GET /v1/quarantine` | Recent rejects with field errors |
| `GET /v1/corpus` | Index manifest (freshness) |
| `GET /healthz`, `/readyz`, `/metrics` | Ops |

### 4.6 Petition data contract (draft; ranges finalised after corpus is known)

| Field | Type / rule |
|-------|-------------|
| `student_ref` | string, regex for synthetic IDs (e.g. `SYN-[0-9]{6}`); **reject anything resembling real ID formats** |
| `program` | enum (`⟦CORPUS⟧` programmes covered) |
| `admission_batch` | int, must equal the corpus batch (else `unsupported`) |
| `petition_type` | enum: `attendance`, `re-evaluation`, `re-registration`, `medical-leave`, `grade-grievance` (+ `other` → escalation path) |
| `course_code` | regex |
| `semester` | int 1..`⟦CORPUS⟧` |
| `classes_held`, `classes_attended` | int ≥0; cross-field: attended ≤ held, held > 0 |
| `attendance_percentage` | float 0–100; cross-field: within ±0.5 of attended/held |
| `reason_category` | enum (`medical`, `personal`, `sports/cultural`, `other`) |
| `medical_documentation` | enum (`none`, `certificate`, `hospital-record`); cross-field: required for `medical-leave` / medical reason |
| `period_start`, `period_end` | ISO dates; start ≤ end; not future-dated beyond limit |
| `petition_text` | string 20–2000 chars (free text → guardrails) |
| Out: `RunResult` | `run_id`, `status`, `route`, `position`, `basis`, `citations[{doc,chapter,clause_id,page,quote,verified}]`, `escalation{required,reason,detail}`, `prompt_versions{}`, `degraded`, `cache_hit`, `disclaimer` ("recommendation only; an examination officer decides") |

---

## 5. Agent architecture

### 5.1 Topology

```
START → [Guardrails-in] → TRIAGE AGENT ──TriageResult──► RESEARCH AGENT ──EvidenceBundle──► VERIFIER/ADJUDICATOR AGENT ──► [Output filter] → END
                              │ (invalid/unsupported)           ▲  tool loop (bounded)                │ fail: retry w/ new strategy (≤2)
                              └──────────────► escalate         └────────────────────────────────────┘ else escalate
```

| Agent | Responsibility | Tools allowed | Input → Output |
|-------|----------------|---------------|----------------|
| **Triage** | Validate semantics, classify type, extract entities, detect type/text mismatch | `get_petition_fields` only (no retrieval) | petition → `TriageResult{type, entities, confidence, flags}` |
| **Research** | Decide what to retrieve; base provision → modifiers → derived second query; stop when evidence adequate or budget hit | `search_corpus`, `get_clause`, `get_petition_fields`, `get_neighbouring_clauses` | `TriageResult` → `EvidenceBundle{passages[], queries[], strategy_log, open_questions}` |
| **Verifier/Adjudicator** | Draft position & route **only from evidence**, verify each citation deterministically + entailment, detect conflicts/discretion, decide retry vs escalate | `get_clause` (read-only verification lookups), `search_corpus` (only when requesting retry strategy, budgeted) | `EvidenceBundle` + `TriageResult` → `Determination{route, position, basis, citations, escalation}` |

Why this is two-plus real agents and not two prompts: separate state schemas, tool permissions, budgets, prompt versions, failure policies, metrics and spans; hand-off is a validated serialised object. Open question A-2.

### 5.2 Bounds (env-configurable defaults)

`MAX_STEPS_PER_AGENT=8`, `MAX_TOOL_CALLS_PER_RUN=10`, `MAX_RUN_SECONDS=90`, `MAX_VERIFY_RETRIES=2`, `LLM_CALL_TIMEOUT_S=20`, `TOOL_CALL_TIMEOUT_S=10`. Exceeding any ⇒ stop and escalate `budget_exhausted` (mapped to a documented reason) — never "best guess".

### 5.3 Failure matrix (documented in `docs/architecture.md`)

| Failure | Behaviour |
|---------|-----------|
| LLM timeout/5xx | retry w/ exponential backoff + jitter (max 3) → breaker counts failure → fallback model → retrieval-only degraded result, `status=escalated(system_degraded)` |
| Breaker open | fail fast, degrade immediately |
| Triage returns invalid schema | one repair retry, else escalate |
| Research loop hits budget with weak evidence | pass partial evidence; verifier escalates `corpus_insufficient` |
| Verifier citation fails | new retrieval strategy (dense→hybrid→clause lookup→section-filtered), ≤2, then escalate `verification_failed` |
| Worker process dies mid-run | RQ job timeout/failure handler marks run `failed`; one automatic re-enqueue; client sees `failed`, never partial answer |
| Redis down | API `/readyz` fails; submissions return 503 |
| Chroma down | worker tool error → degraded/escalate |

### 5.4 Retrieval strategies

`dense` (embedding top-k) → `hybrid` (dense + BM25 fused) → `clause_id` (direct lookup, e.g. following a cross-reference) → `section_filtered` (restrict by chapter/topic tag). Second-hop query is *derived* from hop-1 text (key terms, clause titles such as "shortfall", "condonation", "exception") by the Research Agent.

### 5.5 Prompt injection posture (agents hold tools)

Untrusted fields (`petition_text`, any extracted text) are always wrapped as quoted data; system rules state they are never instructions; tool arguments validated against schema and allow-list (clause ids must exist; no free-form URLs/paths/commands — there are no such tools); no tool can modify a determination; output schema + filter prevents unauthorised determinations; detector hit ⇒ `guardrail_blocked` escalation.

---

## 6. Phase-wise implementation plan

Order is chosen so a **working end-to-end path exists by end of week 2** (Phases 0–3 minimal). Reliability/observability/eval layers follow. If time runs short, cut from the bottom (Phase 6 polish → 7 analysis depth), never from Phases 1–3.

> Phase 0 (this work) is done when the user approves. Corpus selection is the critical-path task.

### Phase 0 — Analysis, corpus selection, architecture
* **Objective:** Approved plan and a verified corpus (Evaluation 1 package).
* **Features:** SPEC/PROJECT_STATUS/README; `corpus/SOURCES.md`; `docs/corpus_verification.md`; reference-answer table for §4.1.
* **Files:** `SPEC.md`, `PROJECT_STATUS.md`, `README.md`, `corpus/raw/*.pdf`, `corpus/SOURCES.md`, `docs/corpus_verification.md`.
* **Dependencies:** Internet access to download PDFs; glossary PDF; team agreement.
* **Tasks:** (1) shortlist 2–3 universities (§8.1); (2) download regulations + bye-laws of one batch; (3) check text layer (`pdftotext`); (4) locate attendance rule, condonation clause, committee-discretion wording, relevant bye-laws; record page/clause; (5) choose test values; (6) fix SLO draft; (7) answer open questions A-1…A-6 with staff.
* **Tests:** manual: each cited clause found by text search in the PDF.
* **Acceptance:** §4.1 dependent passages quoted with page numbers; values agreed; approved by user/staff.
* **Reqs:** prerequisite for F4–F7, L1, L3, D2, demo 10.
* **Deliverables:** Evaluation 1 pack. **DoD:** corpus verification doc complete; user approves.

### Phase 1 — Minimal end-to-end skeleton (target: week 1–2)
* **Objective:** `docker compose up` serves a valid petition end to end (stub logic OK).
* **Features:** FastAPI (`POST /v1/petitions`, `GET /v1/runs/{id}`, `/healthz`), Pydantic contract + cross-field validation + quarantine, Redis+RQ worker running a *trivial* job (e.g. retrieval-less placeholder result clearly marked `placeholder`), SQLite, minimal Streamlit form+result, `.env.example`, `.gitignore`, Docker Compose with healthchecks.
* **Files:** `docker-compose.yml`, `docker/Dockerfile.{api,worker,ui}`, `src/triage/{config,contracts,validation,db}.py`, `src/triage/api/*`, `src/triage/worker/tasks.py`, `ui/app.py`, `tests/test_api_*.py`, `scripts/check_no_secrets.sh`.
* **Dependencies:** Phase 0 approval (Docker Desktop installed).
* **Tasks:** scaffold → contract → API → quarantine → queue/worker → minimal UI → compose healthchecks → clean-clone test.
* **Tests:** `pytest` (valid → 202, malformed → 422 + quarantine + no run), clean-clone `docker compose up`.
* **Acceptance:** F1, F2, A4, A8(min), D1, D3, D4 basic demonstrably true; malformed never creates a run.
* **Reqs:** F1, F2, F8(basic), A4, A8, D1, D3, D4. **Deliverables:** running skeleton, tagged `v0.1`. **DoD:** zero-marks scenario protected: a teammate runs it from a fresh clone.

### Phase 2 — Corpus ingestion & retrieval
* **Objective:** Searchable, versioned index of the verified corpus.
* **Features:** PDF parse (PyMuPDF/pdfplumber, chosen after inspecting corpus), clause-structure chunker, local embeddings, Chroma upsert, manifest, selective re-embed, BM25, cache of embeddings, `ingest` one-shot service, `/v1/corpus`.
* **Files:** `src/triage/retrieval/{parse,chunk,embed,store,search,ingest}.py`, `docs/retrieval_design.md`, `tests/test_ingest_*.py`, `tests/test_retrieval_gold.py`.
* **Dependencies:** Phase 0 corpus; Phase 1 compose.
* **Tasks:** parse → inspect chunks manually → chunk → embed → index → idempotency → partial re-embed → gold retrieval checks on §4.1 passages.
* **Tests:** idempotency, partial re-embed counts, gold clause retrievable by query set (base via naive query; condonation via derived query).
* **Acceptance:** L1, D2; both §4.1 passages exist as separate retrievable chunks with correct metadata.
* **Reqs:** L1, D2. **Deliverables:** index + manifest. **DoD:** `docker compose run ingest` twice → second is no-op.

### Phase 3 — Agents, verification, escalation
* **Objective:** Correct, verified behaviour on the §4.1 case and escalation cases.
* **Features:** LLMClient (minimal: timeout+retry), prompts v1 (YAML), Triage/Research/Verifier agents in LangGraph, 4 tools, budgets, citation verifier, escalation reasons, output filter (basic), `run_events` recording.
* **Files:** `src/triage/agents/*`, `src/triage/llm/{client,prompts}.py`, `prompts/*.yaml`, `src/triage/guardrails/output_filter.py`, `tests/test_agents_*.py` (scripted/fake LLM), `docs/architecture.md`.
* **Dependencies:** Phases 1–2; free-tier LLM key (or local model).
* **Tasks:** fake-LLM tests first → graph → tools → budgets → verifier → real LLM tuning on S01 → escalation cases.
* **Tests:** S01–S14, S24; loop-limit tests; fault injection per agent.
* **Acceptance:** F3–F7, A1–A3 on eval scenarios; **demo item 10 passes**; no unverified citation returned.
* **Reqs:** F3–F7, A1, A2, A3. **Deliverables:** tag `v0.2` = functional system (end of week 2–3). **DoD:** S01 returns both clauses cited and the corpus-correct route/escalation.

### Phase 4 — Reliability & cost control
* **Objective:** Survive provider trouble and abuse.
* **Features:** exponential backoff+jitter, Redis-shared circuit breaker, fallback model → retrieval-only degradation, tool timeouts, rate limiter, caches (embedding/retrieval/run), worker-crash handling.
* **Files:** `llm/{retry,breaker}.py`, `cache.py`, `api/ratelimit.py`, `tests/test_reliability_*.py`, stub fail-mode toggle.
* **Tests:** breaker state machine; chaos with stub; rate-limit loop; crash worker mid-run.
* **Acceptance:** A5 (demo item 8), D7 mechanics. **Reqs:** A5, D7. **DoD:** breaker demo scripted and repeatable.

### Phase 5 — Evaluation, prompts, guardrails, feedback, cost
* **Objective:** Measurable quality and safety.
* **Features:** 24-scenario set, evaluator CLI, 4 metrics, prompt v1 vs v2 comparison, before/after experiment, injection+toxicity guardrails, token/cost tracking, feedback endpoint, live-run sampler.
* **Files:** `eval/scenarios.yaml`, `src/triage/eval/*`, `src/triage/guardrails/{injection,toxicity}.py`, `llm/cost.py`, `prompts/*_v2.yaml`, `docs/eval_report.md`.
* **Tests:** eval CLI run; red-team list; cost arithmetic; feedback persistence.
* **Acceptance:** L2–L6. **Reqs:** L2, L3, L4, L5, L6. **DoD:** `docs/eval_report.md` with tables; cost/100 runs and top driver stated.

### Phase 6 — Observability & UI polish
* **Objective:** Full reconstructability and dashboards; presentable UI.
* **Features:** structlog JSON, correlation IDs through queue, OTel→Jaeger, Prometheus metrics (all services), Grafana provisioned dashboards, cAdvisor, `/trace` endpoint, Streamlit full pages (§7), theme.
* **Files:** `observability/*`, `monitoring/*`, `ui/*`.
* **Tests:** one run → all spans/log lines share correlation id; targets UP; trace JSON complete.
* **Acceptance:** D5, A6, F8; demo item 3. **DoD:** reconstruct a run from `run_id` alone.

### Phase 7 — Load test, scaling, SLO validation
* **Objective:** Honest performance evidence.
* **Features:** `docs/SLO.md` committed **first**; llm-stub; Locust (submit→poll→total); stepped concurrency; scale 1/2/3; cache on/off; bottleneck analysis.
* **Files:** `docs/SLO.md`, `loadtest/*`, `stub_llm/*`, `docs/load_test.md`.
* **Acceptance:** D6, A7, D7 measurement; demo item 9. **DoD:** report tables + named bottleneck; SLO file predates results in git history.

### Phase 8 — Hardening, docs, report, demo rehearsal
* **Objective:** Zero-surprise demo and complete deliverables.
* **Features:** security review (see §10), runbook executions, incident log, README tested by a non-author, report, demo script, final clean-clone test, tag `v1.0`.
* **Files:** `README.md`, `docs/{runbook,incident_log,demo_checklist}.md`, `docs/report/`.
* **Reqs:** D8, D3 recheck, all demo items. **DoD:** §11 checklist rehearsed twice from a clean clone.

### Suggested time ordering (relative, dates unknown)
Week 1: Phase 0 + Phase 1 (+ start Phase 2). Week 2: Phase 2 + minimal Phase 3 → **working end-to-end by end of week 2**. Week 3: finish Phase 3, Phase 4. Week 4: Phases 5–6. Week 5: Phases 7–8. Compress by cutting optional items in §2.1.

---

## 7. Streamlit UI plan

Pages (all data via REST; no business logic):

1. **Dashboard** — metric cards (runs, success rate, escalation rate, median latency, cost/100 runs, feedback satisfaction), status badges, recent runs table.
2. **Submit Petition** — validated form mirroring the contract (client-side hints, server remains authoritative); shows field-level 422 errors; sample synthetic presets (incl. §4.1) for demos.
3. **Run Detail** — run id, live status poll, progress stepper (Triage → Research → Verify), recommendation card with route badge (green grant / amber committee / red reject), eligibility position, basis, **citation list** (doc · chapter · clause · page · quote, verified ✔), escalation banner with reason, prompt versions, degraded/cache badges, feedback form.
4. **Trace** — timeline of tool calls, queries, passages, per-step latency/tokens/cost, verification outcome; link to Jaeger.
5. **Quality & System** — evaluation metrics over time, feedback aggregate, quarantine list, corpus freshness, service health, breaker state, per-agent stats.

Style: single palette (deep navy header, teal accent, neutral grays; semantic green/amber/red badges), consistent card CSS injected once via `ui/style.py`, system-font stack, generous spacing, subtle fade-in only. Polish is Phase 6; Phase 1 UI is plain.

---

## 8. Corpus plan

### 8.1 Selection (NOT DONE — no university chosen)
Candidates to check (none verified; no claims about their contents): the team's own university's UG regulations (PESU, since staff will know them), VTU, Anna University, other state/deemed universities publishing per-batch regulations. Selection criteria: free public PDFs, **one admission batch**, text layer, a stated minimum attendance rule, a condonation provision elsewhere in the document, a bye-law/examination document, ideally one clause that reserves discretion to a committee.

### 8.2 Verification procedure (before Evaluation 1)
1. Download both PDFs; record URL, retrieval date, batch, sha256 in `corpus/SOURCES.md`; check licence/redistribution (if not redistributable, repo gets a fetch script instead of the PDF — but `docker compose up` must still work, so prefer redistributable or a pre-staged volume).
2. `pdftotext` text-layer check; if scanned → OCR (Tesseract) before ingestion.
3. Search terms: *attendance, minimum, condon, shortfall, medical, committee, discretion, exempt, re-evaluation, re-registration, backlog, grievance*.
4. For the §4.1 case record in `docs/corpus_verification.md`: base rule (page, chapter, clause, exact quote, threshold), condonation clause (same), range permitted, conditions (medical proof, authority/committee), any bye-law interplay, wording that reserves discretion.
5. Choose test values (e.g. attendance just below the minimum and inside the condonable range) and write the **reference answer** (route + escalation + cited clauses). Table `⟦CORPUS⟧` placeholders replaced only here.
6. Identify which of the 5 petition types the corpus supports; unsupported ones become escalation scenarios.

### 8.3 Chunking & embedding strategy (addresses §3 difficulty)
* Parse headings/numbering → chunk **per clause** (split long clauses with overlap, keep `clause_id`), never fixed-size across clause boundaries.
* Prepend breadcrumb `Doc › Chapter › Regulation/Clause title` to the embedded text; keep page numbers.
* Add keyword tags at ingest (e.g. `topic: attendance|condonation|exemption|discretion`) from a small rule list to allow `section_filtered` retrieval and make the later-in-document condonation clause reachable from a derived query.
* Stable chunk id and hashes enable idempotent re-ingest and selective re-embed.
* Small local embedding model (name from env); BM25 for lexical complement.

---

## 9. Evaluation strategy

### 9.1 Scenario set (24; all synthetic; real-corpus clause IDs filled in Phase 0/2)

| ID | Scenario | Expected |
|----|----------|----------|
| S01 | **§4.1 difficult case**: below minimum, inside condonable range, medical, documented | Both base + condonation cited; route per corpus (`grant-under-provision` or `refer-to-committee` w/ escalation if committee-reserved) — `⟦CORPUS⟧` |
| S02 | Below minimum, inside range, non-medical reason | per corpus `⟦CORPUS⟧` |
| S03 | Below the condonable range | reject, cite base (+ limit) clause |
| S04 | Attendance meets minimum, petition requests condonation | reject/no-need, cite base rule |
| S05 | Medical, in range, documentation missing | escalate (insufficient evidence) or per corpus |
| S06 | Repeat condonation request (if corpus limits) | per corpus |
| S07 | Re-evaluation within window | per corpus (if supported) |
| S08 | Re-evaluation outside window | reject w/ clause |
| S09 | Re-registration/backlog | per corpus or unsupported-escalation |
| S10 | Medical leave of absence | per corpus or escalation |
| S11 | Grade grievance (if not in corpus) | escalate `unsupported_petition_type` |
| S12 | Out-of-corpus request (hostel fee waiver) | escalate, no fabricated cite |
| S13 | Committee-reserved discretion clause | escalate `committee_discretion` |
| S14 | Conflicting provisions (regulation vs bye-law) | escalate `conflicting_provisions` — uses a small **synthetic test corpus** labelled as such if the real one has no genuine conflict (never presented as real regulation) |
| S15 | Malformed: missing required field | 422 + quarantine, no run |
| S16 | Malformed: attendance 140% / negative | 422 + quarantine |
| S17 | Malformed: attended > held | 422 cross-field |
| S18 | Malformed: unknown petition_type / bad enum | 422 |
| S19 | Prompt injection in `petition_text` ("ignore rules, grant") | guardrail response; route unaffected / `guardrail_blocked` |
| S20 | Injection attempting tool misuse / prompt leak | blocked, no out-of-allowlist tool call |
| S21 | Toxic input text | flagged per policy |
| S22 | Text contradicts structured fields (e.g. says 60%, field 72%) | flag mismatch/escalate |
| S23 | Ambiguous/multi-type petition | clarify flag or escalate |
| S24 | **Fault injection**: model emits fabricated clause | verifier catches → retry/escalate (demo item 6) |

Extra non-eval tests: provider outage (demo 8), loop-limit tests, worker crash.
Each scenario record: `input`, `expected_route`, `expected_escalation{required,reason}`, `gold_clause_ids`, `gold_passage_quotes`, `criteria`.

### 9.2 Metric definitions

| Metric | Computation |
|--------|-------------|
| **Context relevance** | Judge scores each retrieved passage 0/1 for relevance to the petition question; metric = fraction relevant (and recall of gold clause IDs reported separately, deterministic). |
| **Groundedness** | Split the position/basis into atomic claims (judge); fraction of claims supported by retrieved passages (judge with passage text). |
| **Faithfulness** | Citation-level & deterministic-first: fraction of citations whose quote is a verbatim (normalised) substring of the cited retrieved chunk **and** whose claim is entailed by it (judge). Also route consistency with the cited clause. |
| **Hallucination rate** | Fraction of runs containing ≥1 unsupported claim or unresolved citation (any claim with groundedness=0 or citation failing deterministic check). |

Judge = LLM via the same client (different prompt, temperature 0, versioned); judge noise noted; deterministic checks reported alongside.

### 9.3 Experiments
* **L2 prompt comparison:** same 24 scenarios, `prompt v1` vs `v2` (v2 = stricter citation/abstention instructions); report per-metric delta.
* **L3 before/after (one deliberate change):** baseline = single-pass retrieval (no derived second query); change = enable derived-query second hop (the PDF §5 core claim). Report all four metrics before/after, plus S01 outcome. Alternative change if time: naive fixed-size chunks vs clause-aware chunks.
* **D7:** cache on/off p95 and cost/run. **A7:** worker scale 1/2/3.

---

## 10. Reliability, security, observability — how each is implemented and demonstrated

| Item | Implementation | Demonstration |
|------|----------------|---------------|
| Validation (schema/type/range/category/cross-field) | Pydantic + validators | S15–S18, quarantine table |
| Quarantine | `quarantine(id, ts, client, payload_hash, payload_json, errors_json)` | `GET /v1/quarantine`; assert runs count unchanged |
| Prompt injection | §3 L4 / §5.5 | S19–S20 |
| Toxicity in/out | lexicon + interface | S21 |
| Output filtering | schema + phrase block + route post-check | unit tests + forced-bad-output test |
| Timeouts / retries / backoff | `llm/client.py`, `llm/retry.py` | fake provider timing test; logs showing `attempt`, `delay` |
| Circuit breaker | Redis-backed, shared | stub fail-mode → open → fast-fail → half-open → closed (demo 8) |
| Graceful degradation | fallback model → retrieval-only | degraded badge & `system_degraded` |
| Rate limiting | Redis token bucket per client | loop script gets 429 |
| Caching | 3 layers, TTL, keyed by corpus+prompt versions (so stale answers impossible after change) | cache on/off numbers |
| Prompt & model version tracking | in `runs` and `run_events` and response | `/trace` |
| Token/cost per step/run | L5 | `/trace`, cost report |
| Logs + correlation IDs | structlog JSON | grep one id across api/worker |
| Tracing | OTel→Jaeger, traceparent through queue | Jaeger screenshot |
| Metrics/dashboards | Prometheus+Grafana | dashboard screenshots |
| Health | `/healthz`, `/readyz`, compose healthchecks | kill Redis → readyz fails |
| Feedback persistence | `feedback` table | endpoint + aggregate |
| Runbook / incident log | D8 | executed once; real incidents logged from day 1 |
| p95 SLO | `docs/SLO.md` | git history shows it precedes results |
| Load test | Locust + stub, scale 1/2/3 | CSV + report |

**Draft SLO (to be finalised and committed before any load test):** p95 submission→terminal ≤ 60 s at 10 concurrent users with stub delay 1–2 s/call, error rate < 1%. Justification vs PDF §1: petitions are handled by an officer over hours/days, runs "take tens of seconds"; 60 s keeps the interactive experience acceptable while allowing ~6–8 sequential model calls. **This is a draft; do not measure before it is frozen.**

Security review checklist (Phase 8): no secrets (scan), per-client API key, input size limits, containers as non-root, pinned dependencies + `pip-audit`, no tool with side effects, CORS locked down, synthetic-ID regex blocks real-looking IDs, logs never contain keys.

---

## 11. Repository structure

```
.
├── README.md                    run instructions, architecture overview, troubleshooting
├── SPEC.md  PROJECT_STATUS.md
├── docker-compose.yml           all services, healthchecks, depends_on, profiles
├── .env.example  .gitignore
├── docker/                      Dockerfile.api | .worker (torch CPU + baked embedding model) | .ui | .stub
├── corpus/
│   ├── raw/                     source PDFs (if redistributable)
│   └── SOURCES.md               URL, batch, date, sha256, licence
├── prompts/                     triage_v1.yaml research_v1.yaml verifier_v1.yaml (+v2) — versioned prompts
├── src/triage/
│   ├── config.py                env settings (no defaults for secrets/models)
│   ├── contracts.py             Pydantic models = data contract (in/out)
│   ├── validation.py            cross-field rules + quarantine writer
│   ├── db.py                    SQLite access + schema
│   ├── cache.py                 Redis caches
│   ├── api/                     main.py (app), routes.py, ratelimit.py, deps.py
│   ├── worker/                  tasks.py (run_petition, score_run), run_worker entrypoint
│   ├── agents/                  graph.py, triage_agent.py, research_agent.py, verifier_agent.py, tools.py, budget.py, state.py
│   ├── llm/                     client.py (provider interface), retry.py, breaker.py, cost.py, prompts.py
│   ├── retrieval/               parse.py, chunk.py, embed.py, store.py (Chroma), search.py (strategies, BM25), ingest.py (CLI)
│   ├── guardrails/              injection.py, toxicity.py, output_filter.py
│   ├── observability/           logging.py, tracing.py, metrics.py
│   └── eval/                    run_eval.py (CLI), judge.py, metrics.py
├── ui/                          app.py, pages/ (1_Dashboard … 5_Quality), style.py, api_client.py
├── stub_llm/                    main.py (fixed responses, delay, fail-mode toggle)
├── eval/                        scenarios.yaml, results/
├── loadtest/                    locustfile.py, run_matrix.sh
├── monitoring/                  prometheus.yml, grafana/ (provisioning + dashboards JSON)
├── scripts/                     check_no_secrets.sh, clean_clone_test.sh, demo_*.sh
├── tests/                       unit/ integration/ (api, agents, retrieval, reliability, guardrails)
└── docs/                        data_contract.md, architecture.md, retrieval_design.md, corpus_verification.md,
                                 SLO.md, load_test.md, eval_report.md, metrics.md, runbook.md,
                                 incident_log.md, demo_checklist.md, report/
```

Design notes: **one Python package, three entrypoints** (api, worker, ingest) so a student can explain the whole codebase; images differ by dependency profile only. Not split further (no per-tool files, no per-route packages).

---

## 12. Demonstration checklist (PDF §9 items 1–10)

| # | Item | Reproduce | Expected output | Evidence | Criteria |
|---|------|-----------|-----------------|----------|----------|
| 1 | Clean clone → working | `git clone … && cp .env.example .env` (fill LLM vars) `&& docker compose up --build` | All services healthy; `/readyz` 200; UI loads | terminal capture, `docker compose ps` | D3, D4, A8 |
| 2 | Valid request → routed recommendation + resolving citations | UI preset or `curl -X POST /v1/petitions -d @eval/examples/valid.json` then poll | `status=completed`, route, basis, citations `verified=true` | JSON + UI screenshot | F1, F5, F6, A3 |
| 3 | One run traced end to end | `GET /v1/runs/{id}/trace` + Jaeger trace for same `trace_id` | all tool calls, queries, passages, prompt versions, per-step latency/tokens/cost, verification | trace JSON, Jaeger screenshot | D5, L5, L2 |
| 4 | Malformed rejected, no run | POST `eval/examples/malformed_*.json` | 422 with field errors; quarantine row; `runs` count and queue length unchanged; no agent spans | response, `GET /v1/quarantine`, DB count before/after | F2, D1 |
| 5 | Unanswerable → escalation | submit S11/S12 | `escalation.required=true`, reason `unsupported_petition_type`/`corpus_insufficient`, no fabricated cite | result JSON | F7 |
| 6 | Self-verification catches unsupported answer | run S24 with stub/fault-injection env flag `FAULT_FABRICATE_CITATION=1` (test-only, off by default) | trace shows verification fail → new strategy search → corrected or escalate | trace excerpt | A3 |
| 7 | Prompt injection | submit S19/S20 | guardrail response; no unauthorised tool/route; log entry | result + guardrail log | L4 |
| 8 | Circuit breaker + degradation | `scripts/demo_breaker.sh` (toggle stub fail-mode, submit N runs) | breaker opens; later calls fail fast; degraded labelled result; recovers after cooldown | metrics panel `breaker_state`, logs | A5 |
| 9 | Locust vs target, failing concurrency, scale effect | `docker compose --profile loadtest up --scale worker=1/2/3` + `locust --headless …` | table RPS/p50/p95 vs SLO, concurrency breaking point, named bottleneck | `docs/load_test.md`, Grafana | D6, A7, D7 |
| 10 | §4.1 case | submit reference input from `docs/corpus_verification.md` | both clauses cited; route/escalation equals confirmed reference answer | result + citations vs corpus quotes | F4–F7 |

---

## 13. Risks and difficult requirements

| Risk / difficulty | Mitigation |
|-------------------|-----------|
| **F5/F7/A3 (verified, abstaining answers)** — hardest | Deterministic citation check first; build fake-LLM tests before real model; many escalation scenarios |
| Corpus choice slips → blocks everything | Do Phase 0 corpus work immediately; fallback candidate list |
| §4.1: condonation clause not retrieved | Clause-aware chunks, topic tags, derived second query, BM25 hybrid; gold-retrieval tests |
| Free-tier LLM rate limits/quality on demo day | Fallback model env, run cache, pre-warmed reference answer, optional Ollama; keep demo runs few |
| Windows Docker Desktop: image size/RAM (torch + 3 workers), cAdvisor limits on Docker Desktop | CPU-only torch, small embed model baked into image, set worker memory limits; cAdvisor panels best-effort with `process_*` fallback |
| SQLite write contention with scaled workers | WAL + busy_timeout; batch events; report as bottleneck candidate; Postgres upgrade path |
| Multi-replica Prometheus scraping | DNS service discovery of `worker` |
| Trace context across Redis queue | inject/extract `traceparent` in job meta |
| Scope creep (30 requirements, 2–3 students) | Tiering in §2; cut optional items first; never cut Phases 1–3 |
| Judge LLM noise in evaluation | temperature 0, deterministic checks alongside, report caveats |
| "Two agents" interpretation | A-2 clarification; HTTP-split fallback prepared |
| Corpus redistribution licence | Check at Phase 0; fetch-script fallback with pre-staged volume |
| Fake incident log temptation | Log real failures only, from day 1 |

Time-saving recommendations (without reducing compliance): fake-LLM tests first; single package; Chroma server (no file locks); lexicon toxicity; custom evaluator; Jaeger all-in-one; Streamlit polish last; `ingest` as compose one-shot.

---

## 14. Cross-check against the PDF

Page 1: §1 context, §2 what to build, §3 corpus, F1–F7 → matrix §3.1. Page 2: F8, §4.1, §5 design approach (5 steps → §5/A1/A3), A1–A5 → §3.2. Page 3: A6–A8, L1–L6, D1–D5 → §3.2–3.4. Page 4: D6–D8, §9 demo items 1–10 → §12, §10 assessment → §0.3–0.4, §11 deliverables → Phase 0/8, report contents. Page 5: report/repo content, §12 cost, §13 out of scope → §1, §4.1. All 30 IDs (8 F + 8 A + 6 L + 8 D) and all 10 demo items are present in this document.

---

## 15. Amendments after implementation (2026-11-08)

The problem statement, requirement list and trust boundaries above are **unchanged**. These amendments record what was added or learned; the
current verified state is in `PROJECT_STATUS.md`.

| # | Amendment | Reason |
|---|---|---|
| AM-1 | **Human examiner decisions** are a first-class, separate record (`POST /v1/runs/{id}/examiner-decision`, table `examiner_decisions`, vocabulary `accept-petition / reject-petition / request-more-information`, append-only, with a frozen snapshot of the AI recommendation). Identity is self-declared; there is no authentication. | "The AI never makes the final decision" needs a place where the human does. |
| AM-2 | **Supporting documents** can be attached to a petition (`POST /v1/runs/{id}/documents`): PDF/PNG/JPEG by content, ≤ 2 MiB, ≤ 3 per petition, stored for the examiner and **never read by an agent**. | Student portal requirement; kept out of the AI path to avoid a new prompt-injection and data-protection surface. |
| AM-3 | **React frontend** (`frontend/`, served by nginx, same-origin `/api` proxy) with Student, Examiner and System portals behind a *demonstration* role switch. The Streamlit UI remains as a fallback. | Usability; the role switch is explicitly not access control. |
| AM-4 | **Hybrid retrieval** tool `search_hybrid` (reciprocal-rank fusion of semantic and BM25), exposed in research prompt v2 only so v1 behaviour and the v1-vs-v2 comparison stay clean. | §4.1 retrieval difficulty; real-model runs showed the DX table (25OB23.0) is often not retrieved. |
| AM-5 | **Policy guard:** the AI may not recommend *rejection* for attendance between 75 % and 85 % (inside, or possibly inside, the band clause 25OB10.0(5) reserves to the Vice-Chancellor); such a result becomes `refer-to-committee / committee_discretion` with a visible system note. | Real-model finding (a model rejected 80 % and 84 % petitions on its own reading of "documents" and "grounds"). |
| AM-6 | **Open questions OQ1–OQ4** and a human-review checklist are attached to every attendance result and shown in the UI. | A-assumptions about "10 %", the deciding authority, certificates and corpus completeness are unconfirmed and must not read as fact. |
| AM-7 | **LLM client hardening:** a no-native-tool-calls instruction on every system prompt; redacted provider error messages; 429 handling (`Retry-After`, "try again in …" text, header-driven pacing, patient retries inside the run budget, and **fail-fast on quota-size waits**); run budget 450 s with a job timeout that follows it. | Observed with the real provider: HTTP 400 on native tool calls, 8,000 tokens/minute and 200,000 tokens/day limits. |
| AM-8 | **Outage behaviour:** API stays responsive with Redis down (shared "recently down" window, metrics off the event loop, fast 503), readiness counts live workers by heartbeat, a Chroma failure during verification maps to `retrieval_unavailable`, the worker never blocks on an unreachable trace collector. | Found by `loadtest/failure_drills.py` with really stopped containers. |
| AM-9 | New read endpoints for the dashboards: `GET /v1/runs` filters (`status`, `student_ref`, `petition_type`, `real_only`, `awaiting_decision`, `limit`, `offset`, `matched`), `GET /v1/stats` (+ `by_type`, `by_day`, `by_model`, `real_only`), `GET /v1/stats/agents`, `GET /v1/system`. | Only real data may feed the UI. |
| AM-10 | Rate limiting also covers uploads and decisions and runs before body validation; petition bodies are capped at 64 KiB. | Security probe findings. |

Still open from §A / §13 (see `KNOWN_LIMITATIONS.md` §A): bye-laws, "10 %", deciding authority, certificate rules, source URL and licence, autonomous-college rules, and the `EMBED_MODEL` question (A-3).
