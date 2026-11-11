# Testing report

Run on 2026-11-11 on the author's machine (Windows 11, Python 3.14.6, Node 22, Docker Desktop). Previous documents quoted earlier checkpoints; all figures below were re-run and verified in the current final engineering pass.

## 1. Summary

| Suite | Command | Result |
|---|---|---|
| Python, full suite on the **final code** | `python -m pytest -q -rs -m "not env_gated"` | **251 passed, 5 skipped, 0 failed** (2 min 41 s) |
| The 5 skipped tests, run with their environment enabled | `EMBED_MODEL=… LLM_*=… python -m pytest -q -m "realmodel or realllm"` | **5 passed** (4 real-embedding retrieval tests on the real PDF; 1 real-LLM end-to-end smoke test) → **256 / 256** |
| Frontend unit tests (Vitest + Testing Library) | `cd frontend && npm test` | **18 passed** |
| Frontend type-check and production build | `cd frontend && npm run build` | **passes with code 0** (`tsc -b && vite build`) |
| Browser end-to-end (headless Chromium, clean-copy stack, stub LLM) | `e2e/petition_flow.mjs` | **18 / 18** checks (`docs/e2e_results.json`) |
| Black-box security probe against the running stack | `scripts/security_probe.py` | **28 / 28** (`docs/security_probe_results.json`) |
| Observability verification (Prometheus, Grafana, Jaeger) | `scripts/verify_observability.py` | **20 / 20** (`docs/observability_check.json`) |
| Failure / recovery drills (real container stop/start) | `loadtest/failure_drills.py` | **5 / 5** after fixes (1 / 5 before; see `LOAD_TEST_REPORT.md` §5–6) |
| Load tests | `loadtest/benchmark.py` | 12 configurations, see `LOAD_TEST_REPORT.md` |
| Scripted evaluation (28 scenarios) | `python -m triage.evaluation.run --mode scripted` | **28 / 28** |
| Real-LLM evaluation (19 scenarios) | `--mode real` | **14 / 19** (gpt-oss-120b) and **16 / 19** (qwen3.8-27b); see `docs/EVALUATION_REPORT.md` |
| Secret scan | `python scripts/check_no_secrets.py` | **ok (382 files scanned, 0 secrets)** |

No test was deleted, weakened or newly skipped.

## 2. Python tests by area (256 tests total)

| File | Tests | Covers |
|---|---|---|
| `test_agents.py` | 44 | three-agent hand-offs, tool choice, budgets, citation verification (exact/fabricated/paraphrased), guardrail blocks, escalation reasons, unsupported types, **reject-inside-band guard**, **hybrid retrieval (RRF) and tool allow-list**, real-LLM smoke (gated) |
| `test_api_phase1.py` | 22 | validation, quarantine, 422 field errors, queue, status, health/readiness, corpus status |
| `test_examiner.py` | 17 | **human decision stored separately and append-only**, documents (type by content, size, count, duplicate, filename sanitising, safe download headers), run filters, stats breakdowns, `/v1/system`, body-size cap, **rate limiting incl. invalid bursts**, duplicate petitions, **server-side `real_only` / `awaiting_decision` filters** |
| `test_reliability.py` | 44 | retry/backoff, `Retry-After`, **quota 429 fail-fast**, rate-limit pacing, circuit breaker, fallback, caches, **API behaviour with Redis down**, **live-worker counting**, **Chroma failing during verification**, stale-run threshold, secret redaction of provider errors |
| `test_guardrails.py` | 27 | injection, abuse, tool arguments, numeric-claim check, output filter |
| `test_retrieval.py` | 22 | parsing, clause-aware chunking, idempotent ingest, stale removal, embedding migration, BM25/semantic/clause retrieval |
| `test_final_qa.py` | 17 | ambiguity, contradictions, injection quoting, regression cases from earlier QA |
| `test_ui.py` | 15 | Streamlit fallback UI (student/examiner views, review flow) |
| `test_evaluation.py` | 12 | scenario integrity, metric definitions, scripted run, **resume/intermediate saving**, judge, auto-eval safety |
| `test_auth.py` | 10 | **Role-based authentication**, bcrypt password hashing, session tokens, student privacy isolation, examiner decision attribution, multi-student profiles, demo credentials, petition seeding |
| `test_observability.py` | 10 | redaction, correlation ids, trace propagation, readiness, metrics format, **non-blocking trace flush** |
| `test_feedback_cost.py` | 9 | feedback, token and cost accounting |
| `test_real_model.py` | 4 | real sentence-transformer retrieval of 25OB10.0(4)/(5) on the real PDF (gated) |
| `test_secrets.py` | 3 | `.env` ignored, no credential patterns in tracked/unignored files |

### Skipped tests (5) and why
Skipped by design unless the environment provides what they need; they were **executed and passed** separately (§1):
`test_real_model.py` ×4 need `EMBED_MODEL` (local embedding model); `test_agents.py::test_real_llm_smoke` needs `LLM_BASE_URL` / `LLM_MODEL` (and a key).

## 3. Frontend tests (13)

Rendering of the recommendation panel (citations, escalation, uncertainty text, examiner-only vs student-visible content, stub-model warning, no-determination, running/failed states),
pipeline stepper, API client error mapping (422 field errors, unreachable backend, 429 with `Retry-After`), and the new-petition form (blocks and explains invalid input without calling the API,
calculates attendance, explains unsupported categories, submits a valid petition and shows the confirmation). The fixture objects are test **inputs**; the shipped app contains no mock data.

## 4. Browser end-to-end (18 checks, clean-copy stack)

Empty-form validation → valid petition with a PDF upload → confirmation with run id → live tracking until the AI finishes → recommendation labelled "not a decision" and "a human examiner must review" →
document listed → examiner queue search → review page shows petition and document → decision form refuses an empty submit → decision recorded and shown in history next to the unchanged AI recommendation →
student page shows the examiner's decision → system overview renders → no horizontal scroll at 390 px on three pages → mobile navigation drawer → zero console errors.
Run against a **throwaway** install (separate Compose project and volumes) because it writes a test petition and a test examiner decision.

## 5. Tests that were changed (and why)

| Test | Change | Reason |
|---|---|---|
| `test_agents.py::test_verification_failure_followed_by_corrected_answer` | uses a 72 % petition instead of the default 80 % | It tests the citation-retry loop with route `reject`; 80 % is now (intentionally) converted to a referral by the new guard. Assertions unchanged. |
| `test_reliability.py::test_backoff…` | cap for a provider `Retry-After` is now 30 s (was 8 s) | Deliberate behaviour change so token-per-minute limits are honoured. |
| `test_reliability.py::test_stale_running_run…` | patches `stale_after_seconds` instead of a constant | Threshold became a function of the run budget. Assertion unchanged. |
| `test_ui.py::nav` helper and `test_streamlit_shows_error_state_when_api_down` | switches to the Examiner view first | The Streamlit UI gained Student/Examiner views; the Student landing page makes no API call. |
| `conftest.py` | resets the process-global "Redis recently down" window around every test | Prevents one outage simulation leaking into later tests. |

## 6. Bugs found by testing and fixed this session

Real-model: provider HTTP 400 on native tool calls (prompt note; larger model) · `null` fields from models · quota/TPM handling and pacing · model **rejecting** petitions inside the Vice-Chancellor-reserved band.
Load/drills: blocking trace flush (4× throughput loss) · API hang with Redis down · stale worker count in readiness · Chroma outage mislabelled `agent_error` · slow orphan detection.
Security probe: rate limit not applied before body validation · nginx security headers dropped per location.
UI: "Review" opened with an empty run id (Streamlit key state) · mobile overflow from grid card sizing · acronym casing.
Tooling: secret scanner flagged `node_modules` and the build output (now git-ignored) · benchmark crashed on non-UTF-8 Docker output.

## 7. Not covered

Firefox / Safari, screen readers, keyboard-only walkthrough · mutation or property-based testing · a real-model run of the reject-in-band guard (verified by unit and scripted tests only; the real models in the final run did not reject those petitions) ·
`pip-audit` re-run · tests against a paid LLM tier · Windows-only quirks on Linux/macOS hosts.
