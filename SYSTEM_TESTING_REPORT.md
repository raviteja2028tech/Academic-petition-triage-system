# System testing report

End-to-end evidence for the whole application (API, queue, worker, agents, retrieval, real LLM, UI, Docker, observability, failure handling).
Unit-level results are in `TESTING_REPORT.md`; performance is in `LOAD_TEST_REPORT.md`; evaluation tables are in `docs/EVALUATION_REPORT.md`.
Date: 2026-11-08. Everything marked **Verified** was executed in this session.

## 1. Real-LLM end-to-end run (the difficult case)

Petition: synthetic, attendance, 80 % (80/100), medical, certificate declared. Submitted through the HTTP API → Redis/RQ → worker → three agents → real provider
(`openai/gpt-oss-120b` via an OpenAI-compatible endpoint) → result read back from the API. Run `run_babba1674d7844e3`:

| | |
|---|---|
| Outcome | `escalated` · route `refer-to-committee` (displayed as "refer to the deciding authority") · reason `committee_discretion` |
| Position (model text) | "attendance (80 %) falls below the required 85 % but is within the 10 % shortage that may be condoned on medical grounds, requiring discretionary approval" |
| Verified citations | **25OB10.0(4), p. 18** – "A student who cannot fulfil 100 % attendance shall be required to secure a minimum attendance of 85 % in each registered course." · **25OB10.0(5), p. 19** – "a shortage up to a maximum of 10 % may be condoned by the Vice-Chancellor, based on the specific recommendations…" |
| Effort | 12 provider calls (1 triage, 8 research, 3 verifier), ≈ 22k tokens, 142 s end-to-end (provider token-rate pacing: 6 rate-limit waits) |
| Self-correction | The verifier **rejected** the model's first citation for 25OB10.0(5) (the quote was not verbatim in the passage), sent the run back to research, and accepted the second attempt. One model reply with an invalid field (`escalation.detail: null`) was repaired by a retry. |
| Uncertainty preserved | Result carries 4 open questions (meaning of "10 %", decision maker, what a certificate proves, corpus completeness) and a human-review checklist; the UI states that the position is a proposal. |
| Human step | Examiner portal shows the petition, documents, citations and pipeline trace; a decision is recorded separately (browser E2E). |

Also verified with real models: all three agents and the verifier retry path (§2), the full 19-scenario run on two models (`docs/EVALUATION_REPORT.md`), and the env-gated smoke test (`test_real_llm_smoke`).
**Not verified with a real model:** the new "no AI rejection inside the discretionary band" guard (unit and scripted tests only).

## 2. Requested scenarios → evidence

| # | Scenario | Evidence | Result |
|---|---|---|---|
| 1 | 80 % attendance, medical certificate | §1; eval S01 passes on gpt-oss-120b, qwen3.8-27b and scripted | **Escalated to a human with verified citations** |
| 2 | 80 % attendance, no documents | eval S06: gpt-oss-120b **rejected** (route differs from expectation) → guard added and unit-tested; qwen **escalated** (pass); scripted pass | Safe after fix; the real-model guard run was not possible (daily quota) |
| 3 | 72 % attendance, medical certificate | eval S04: gpt-oss-120b `reject` (route correct, but the DX table 25OB23.0 was not retrieved: recall 0.5); qwen `refer` (conservative, differs from the expected `reject`); qwen + prompt v2 retrieved both gold clauses (recall 1.0) but still `refer`; scripted pass | **Partially verified**; real models disagree with the team's expectation, which itself depends on the unconfirmed "10 %" reading |
| 4 | Normal valid attendance petition | eval S03 (82 %, certificate) passes on both models; S02 (78 %, hospital record) passes | Verified |
| 5 | Invalid petition | HTTP 422 + field errors + quarantine, never queued (tests; probe with 5 malformed bodies; UI inline errors, E2E) | Verified |
| 6 | Incomplete petition | 422 for missing/inconsistent fields (`test_api_phase1`, E2E empty form) | Verified |
| 7 | Unsupported category | eval S08–S11 pass on both real models and scripted: `unsupported_petition_type`, no AI opinion | Verified |
| 8 | Missing regulatory evidence | scripted S15 → `corpus_insufficient`; cannot be induced on a real model | Verified (scripted) |
| 9 | Conflicting clauses | scripted S14 → `conflicting_provisions` | Verified (scripted) |
| 10 | Incorrect citation | scripted S16/S17 → `verification_failed`; **real** occurrence: verifier rejected a non-verbatim quote in §1 and in eval run A (S04) | Verified (scripted + real) |
| 11 | LLM outage | scripted S24/S25; load test `outage_100pct` (103 escalations, all `llm_unavailable`, 0 failed); **real**: daily quota exhaustion → `llm_unavailable` with the provider's message | Verified |
| 12 | Retrieval failure | drill: Chroma stopped → `escalated/retrieval_unavailable`, `NO_DETERMINATION`, 0 citations, recovers; unit tests | Verified |
| 13 | Malformed LLM response | scripted S26 → `invalid_agent_output`; real: invalid JSON/`null` repaired by the retry path | Verified |
| 14 | Prompt injection | eval S18–S21 pass on both real models (escalated `unsafe_input`, **no model call**); S28 (benign instruction words) not flagged | Verified (heuristic) |
| 15 | Duplicate petition | **By design the API creates an independent run for every POST** (pinned by a test); the web form blocks resubmitting an identical, already-accepted petition. No server-side de-duplication. | Behaviour documented, not prevented server-side |
| 16 | Oversized upload | probe: 2 MB + 10 B → HTTP 413; nginx caps at 3 MB; petition JSON > 64 KiB → 413 | Verified |
| 17 | Unsupported file format | probe: HTML/exe/SVG/empty disguised as PDF/PNG → 415 (checked by content) | Verified |
| 18 | Ambiguous regulatory interpretation | every attendance result carries the open questions; scripted S27 → `petition_ambiguous`; real: qwen escalated with `committee_discretion` instead of `petition_ambiguous` (reason differs, still safe); gpt-oss S27 was cut off by rate limiting | Verified (safe); real-model reason varies |

## 3. Failure handling (Docker, containers really stopped)

Source: `loadtest/results/failure_drills.json`. Details and the four defects the first execution exposed are in `LOAD_TEST_REPORT.md` §5–6.

| Failure | System behaviour | Verified |
|---|---|---|
| LLM provider down / quota exhausted | bounded retries; quota errors fail fast; breaker opens; run `escalated/llm_unavailable`, no determination | yes |
| Redis down | submit → 503, readiness 503 (`redis_down`), liveness 200, no hang; recovers | yes |
| Worker down | submissions accepted and queued; readiness reports `no_workers` after ≈ 19 s; queue drains after restart | yes |
| Worker killed mid-run | interrupted run reported `failed` after ≈ 277 s; others complete; nothing stuck | yes |
| Chroma down | `retrieval_unavailable`, no fabricated answer; recovers | yes |
| Empty retrieval | `corpus_insufficient` escalation (scripted S15) | yes |
| API restart | finished runs persist | yes |
| Malformed documents (uploads) | rejected 415, nothing stored | yes |
| Database errors | `/readyz` reports `database: down`; not injected in this session | partly |

## 4. Docker and installation

| Check | Result |
|---|---|
| `docker compose up -d --build` (api, worker, redis, chroma, web, ui; `ingest` one-shot) | all services **healthy**; 197 chunks, 5/5 verified passages |
| **Clean-copy install** in a temp directory (no `.env`, caches, data, `node_modules`) as a separate Compose project with fresh volumes | builds, starts, ingests (24.5 s), serves; `npm ci` + build + tests pass; Python suite 240 passed / 5 skipped (the copy was taken before the last small changes); browser E2E 18/18; torn down with `down -v` (own volumes only) |
| Stop / start (`down` then `up -d`) | runs, index and uploaded files persisted; readiness green in ≈ 45 s |
| Logs | no tracebacks or ERROR lines after startup (a span-export error loop appeared only when `OTEL_EXPORTER_OTLP_ENDPOINT` pointed at a Jaeger that was not running; blank by default) |
| Ports | all published on 127.0.0.1 only (web 8080, api 8000, ui 8501; observability profile 16686/9090/3000/8081) |
| Observability profile | Prometheus targets up; all 23 Grafana panel queries valid PromQL; Grafana healthy with provisioned datasource and dashboard; Jaeger shows a 12-span trace across `triage-api` and `triage-worker` (operations: `POST /v1/petitions`, `worker.process_petition`, `agent.triage/research/verifier`, `llm.call`, `tool.*`) with **no petition text** in span attributes; two panels (`Run error rate`, `fallbacks`) have no series because those events never occurred |

## 5. UI verification

React app (`web`): 18-step browser E2E (desktop and 390 px), screenshots in `docs/screenshots/` (`final_*`); Streamlit fallback: 15 automated tests plus earlier headless-browser review.
Every visible control either works or is labelled: the role switch is labelled "Demo role switch · not authentication"; unsupported petition categories are labelled "Escalates"; the AI-versus-human separation is shown on every petition page.
The dark theme was reviewed visually on the examiner dashboard and review pages only (`docs/screenshots/final_*_dark.png`). Not tested: Firefox/Safari, screen readers, a keyboard-only pass.

## 6. Open items

Real-model verification of the reject-in-band guard · real-LLM evaluation with prompt v2 beyond 3 scenarios · everything listed in `KNOWN_LIMITATIONS.md` (authentication, bye-laws, interpretations, licence).
