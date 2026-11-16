> **Partly superseded (2026-11-08).** This summary was written before the real-LLM work, the React frontend, the examiner decision record and the hardening done since. For the current, evidence-backed status, see `PROJECT_STATUS.md`, `TESTING_REPORT.md`, `SYSTEM_TESTING_REPORT.md`, `LOAD_TEST_REPORT.md`, `SECURITY_REVIEW.md` and `docs/EVALUATION_REPORT.md`.

# Final Report (Summary)

For detailed, authoritative information, see `PROJECT_STATUS.md` (checks actually run), `SPEC.md` (requirement status) and the topic documents in `docs/`.

## Where to find things

| Area | Document |
|---|---|
| Architecture and design | `docs/architecture.md` |
| Corpus and regulatory caveats | `docs/corpus_verification.md` |
| Evaluation | `docs/evaluation.md` |
| Reliability | `docs/reliability.md` |
| Guardrails | `docs/guardrails.md` |
| Observability | `docs/observability.md` |
| Load test | `docs/SLO.md`, `docs/LOAD_TEST.md` |
| Security | `docs/security_review.md` |
| Operations | `docs/runbook.md`, `docs/incident_log.md`, `docs/demo.md` |

## Key results
- **Evaluation:** the scripted evaluation passes 28/28, which tests the safety machinery only. The retrieval experiment showed no effect.
- **Load test:** one worker handles about 0.42 runs/s. With 1, 2 and 3 workers, throughput was 0.42, 0.80 and 1.27 runs/s using an LLM stub. A per-job model-reload bottleneck was found and fixed.

## Key trade-offs
- **Asynchronous queue (RQ):** keeps the submit step fast.
- **Redis:** holds shared state for the circuit breaker, rate limiting, cache and metrics.
- **Citation verification:** citations are checked against the live index rather than trusted.
- **Human escalation:** every doubtful path escalates to a human, with no determination made automatically.
- **Long-lived workers:** the model is loaded once, at the cost of crash isolation.
- **Heuristic guardrails:** simple rules with documented limits.
- **Local embeddings:** avoid the need for paid APIs.

## Limitations
- No real-LLM results.
- Bye-laws are missing, and two interpretations are unconfirmed.
- Only attendance petitions are covered.
- No authentication.
- The evaluation set is small, written by the author and mostly scripted.
- Load results come from one laptop, with a stub LLM and single short trials.
- Several planned benchmarks were not run.
