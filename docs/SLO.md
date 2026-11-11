# Service Level Objectives — FROZEN before any load test was run

**Status: FROZEN.** Written on 2026-10-28, before the first benchmark was executed. The benchmark report records the
SHA-256 of this file; if the hash in a report differs from the current file, the SLO was changed after measurement and
the report must not be used to claim the SLO was met. Targets may only be revised in a *new* dated section below, never
edited in place.

## Why these targets
The workload is an interactive-but-asynchronous triage service: a clerk submits a petition and reviews a recommendation
within seconds to minutes. Nobody blocks on the HTTP request, so the **submit path must be fast and almost never fail**,
while **end-to-end time** only needs to be "comfortably under a minute" for the recommendation to be useful in a
review session. The unit of capacity is a *worker*, because each run is dominated by serial LLM calls (≈ 5 per run:
1 triage, ≥ 2 research, 1 verifier, plus retries) and CPU embedding/BM25 work.

## Test environment (what these targets apply to)
* One developer laptop (Windows 11, Docker Desktop with WSL2 backend), all services on the same host, CPU-only.
* Real API, Redis/RQ queue, workers, SQLite (WAL), Chroma, local sentence-transformers embeddings, real retrieval.
* **Only the LLM is replaced** by `loadtest/llm_stub.py` with a configurable mean latency (default 300 ms ± 30 %).
  Results therefore describe the *system around the model* with a fast, deterministic model; a real hosted LLM adds
  seconds per call and rate limits, so real end-to-end latency will be higher. These SLOs must be re-baselined with a real
  provider before being quoted as production commitments.
* Rate limiting is raised for load tests (`RATE_LIMIT_REQUESTS` high); its behaviour is covered by unit tests.

## SLIs and objectives
| # | SLI | Definition | Objective |
|---|-----|-----------|-----------|
| S1 | Submit success | `POST /v1/petitions` returns 202, over all valid requests (429 excluded; it is tested separately) | ≥ 99.0 % |
| S2 | Submit latency | HTTP latency of that request | p95 ≤ 300 ms |
| S3 | Processing success | runs that reach `completed` or `escalated` (a clean outcome) divided by runs submitted; `failed` and never-finished runs count as failures | ≥ 99.0 % |
| S4 | End-to-end latency, nominal load | submit → terminal status, **1 worker at 0.3 runs/s offered load** | p50 ≤ 6 s, p95 ≤ 12 s |
| S5 | Queue wait, nominal load | time from enqueue to worker start (`queue_wait_seconds`) | p95 ≤ 3 s |
| S6 | Horizontal scaling | saturation throughput (completed runs/s) with 3 workers divided by with 1 worker | ≥ 1.5× |
| S7 | Degraded-mode correctness | with the LLM stub returning errors, runs end `escalated`/`llm_unavailable` (never `failed`, never a fabricated determination) | 100 % |

"Nominal load" is chosen to be **below** the expected single-worker capacity (≈ 0.4 runs/s if a run takes ≈ 2.5 s), so S4
measures service time plus modest queueing, not a saturated queue. Behaviour **above** nominal load (saturation,
queue growth, error onset) is measured and reported but is not an SLO.

## What would count as a miss
Any objective not met in the final report is reported as **missed** with its measured value and the identified cause;
objectives are not rewritten to fit results. If a run of the benchmark could not be executed, the report says so.

## Revision log
* 2026-10-28 — initial version (this document), frozen before benchmarking.
