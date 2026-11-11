> **Superseded in part (2026-11-08).** This summary predates the real-LLM work, the React frontend, the examiner decision record and the hardening done since. Current, evidence-backed status: `PROJECT_STATUS.md`, `TESTING_REPORT.md`, `SYSTEM_TESTING_REPORT.md`, `LOAD_TEST_REPORT.md`, `SECURITY_REVIEW.md`, `docs/EVALUATION_REPORT.md`.

# Final report (summary)

Authoritative detail: `PROJECT_STATUS.md` (checks actually run), `SPEC.md` (requirement status), and the topic documents in `docs/`.

**Architecture and design:** `docs/architecture.md`. **Corpus and regulatory caveats:** `docs/corpus_verification.md`. **Evaluation:** `docs/evaluation.md` (scripted 28/28 = safety machinery only;
retrieval experiment: no effect). **Reliability / guardrails / observability:** `docs/reliability.md`, `docs/guardrails.md`, `docs/observability.md`. **Load test:** `docs/SLO.md`, `docs/LOAD_TEST.md`
(1 worker ~0.42 runs/s; 1/2/3 workers 0.42/0.80/1.27 runs/s with an LLM stub; per-job model reload bottleneck found and fixed). **Security:** `docs/security_review.md`. **Operations:** `docs/runbook.md`, `docs/incident_log.md`, `docs/demo.md`.

## Key trade-offs
Asynchronous queue (RQ) so submit stays fast; Redis for shared breaker/rate-limit/cache/metrics state; citations verified against the live index rather than trusted; every doubtful path escalates to a human with no determination;
long-lived workers (model loaded once) at the cost of crash isolation; heuristic guardrails with documented limits; local embeddings to avoid paid APIs.

## Limitations
No real-LLM results; bye-laws missing and two interpretations unconfirmed; attendance petitions only; no authentication; small, author-written, mostly scripted evaluation; load results from one laptop with a stub LLM and single short trials; several planned benchmarks not run.
