> **Superseded in part (2026-11-08).** `LOAD_TEST_REPORT.md` (root) reports the complete, re-run suite (nominal, cache on/off, faults, workers, concurrency, failure drills) and a throughput bug found and fixed since. The fork-vs-simple worker comparison below was not re-run.

# Load test report

Environment: one 12-CPU Windows 11 laptop, Docker Desktop, everything on the same host. Real API, Redis/RQ, workers, SQLite, Chroma, local embeddings and retrieval; **only the LLM is a stub**
(`loadtest/llm_stub.py`, 300 ms ± 30 % per call, deterministic, ≈5 calls/run). The SLO (`docs/SLO.md`) was frozen before any run (sha256 `9b7460c8651c26ea…`, recorded in `loadtest/results/*/meta.json`).
Reproduce: `python loadtest/benchmark.py --suite <name>`; tables: `PYTHONIOENCODING=utf-8 python loadtest/report.py loadtest/results/main loadtest/results/bottleneck`.
Raw data: `loadtest/results/main/*.json|csv`, `loadtest/results/bottleneck/*`. Each configuration ran **one 45 s trial** (≈16–57 completed runs): indicative only, no repeats, no confidence intervals.

## What was and was not measured
| Planned | Status |
|---|---|
| Concurrency sweep, 1 worker (1/2/4/8 users) | **Run** |
| Workers 1 / 2 / 3 at 12 users | **Run** |
| Fork-per-job vs long-lived worker | **Run** (bottleneck found and fixed) |
| Cache on vs off | **NOT run** (stopped to save time) — cache effect is unmeasured |
| Nominal-load SLO test (0.3 runs/s) | **NOT run** — S4/S5 are **unmeasured** |
| Fault injection under load (20 % errors, 429s) | **NOT run under load**; a 3-petition manual outage test was done instead (see below) |

## Results (stub LLM)
| config | workers | users | throughput runs/s | e2e p50 / p95 (s) | submit p95 (ms) | queue wait mean (s) | failures |
|---|---|---|---|---|---|---|---|
| c1_1w_1u | 1 | 1 | 0.356 | 2.7 / 2.7 | 100 | 0.05 | 0 |
| c1_1w_2u | 1 | 2 | 0.422 | 4.3 / 4.8 | 110 | 1.9 | 0 |
| c1_1w_4u | 1 | 4 | 0.444 | 8.4 / 9.5 | 320 | 5.7 | 0 |
| c1_1w_8u | 1 | 8 | 0.422 | 18.0 / 18.0 | 370 | 12.6 | 0 |
| w1_12u | 1 | 12 | 0.422 | 24.0 / 28.0 | 730 | 18.0 | 0 |
| w2_12u | 2 | 12 | 0.800 | 14.0 / 15.0 | 740 | 9.8 | 0 |
| w3_12u | 3 | 12 | 1.267 | 8.7 / 9.8 | 720 | 5.9 | 0 |

Latency percentiles from Locust are coarse (rounded). Queue-wait p95 comes from fixed histogram buckets (upper bounds). Closed-loop users: latency under load is mostly queue wait.

## Findings
1. **One worker saturates at ≈0.42–0.44 runs/s** (service time ≈ 2.3 s: ≈5 serial stub calls ≈ 1.5 s + retrieval). Throughput is flat from 2 to 12 users; extra users only lengthen the queue (e2e p50 2.7 s → 24 s). Worker utilisation ≈ 0.88–0.94.
2. **Scaling worked in this test:** 0.42 → 0.80 → 1.27 runs/s for 1/2/3 workers (**3.0×** at 3 workers; SLO S6 target ≥ 1.5×: met). Each worker used ≈ 20 % of one core, so the bottleneck is the serial LLM-call latency inside each run, not CPU. With a real LLM (seconds per call) each worker's capacity will be lower, and provider rate limits may cap scaling; not measured.
3. **Bottleneck found and fixed:** stock RQ forks a process per job, so every petition reloaded the embedding model (≈10 s of ≈12 s per run; worker CPU 97 %). Running jobs in the long-lived worker (`WORKER_MODE=simple`, now the default, with model warm-up at start) raised 1-worker throughput **0.067 → 0.422 runs/s** (same 4-user, 45 s configuration; n = 3 vs 19 runs). Trade-off: no crash isolation between jobs; `WORKER_MODE=fork` restores it.
4. **API submit latency** rose with concurrency (p95 100 ms at 1 user → ≈ 730 ms at 12): the API shares the host with all workers and polling load. Not investigated further.

## SLO scorecard (measured only)
| # | Objective | Result |
|---|---|---|
| S1 submit success ≥ 99 % | **Met** in all 7 runs (0 failures) |
| S2 submit p95 ≤ 300 ms | **Met at 1–2 users (≤110 ms); MISSED at ≥ 4 users (320–740 ms)** |
| S3 processing success ≥ 99 % | **Met** (0 failed runs in 7 configs) |
| S4/S5 nominal-load latency & queue wait | **Not measured** |
| S6 3 workers ≥ 1.5× | **Met (3.0×)**, single trial |
| S7 degraded-mode correctness | Manual check only: with the stub returning HTTP 500, 3 of 3 runs ended `escalated`/`llm_unavailable`, no citations, no determination; after 2 failed calls (threshold 2) the breaker opened and the third run failed fast ("circuit breaker is open"); `/readyz` reported `llm_breaker: open`. Not run under load. |

## Caveats
Stub LLM, single laptop, single 45 s trial per point, no cache comparison, no repeat runs. Results describe the system around the model, not a real deployment. `/readyz` `workers` counted 5 after the benchmark restarted workers many times (stale RQ registrations expire after a timeout); the count can briefly overstate live workers.
