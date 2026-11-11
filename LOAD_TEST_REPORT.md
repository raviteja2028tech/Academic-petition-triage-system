# Load test report

Every number below is copied from the raw files under `loadtest/results/final/` (Locust CSVs, API `/metrics` deltas, `docker stats` samples) by
`loadtest/report.py`; the tables are in `loadtest/results/final_tables.md`. Nothing is estimated or typed from memory.

## 1. Scope and honesty notes

* **The LLM is replaced by `loadtest/llm_stub.py`** (≈300 ms ± 30 % per call). Everything else is real: API, Redis/RQ, worker, SQLite, Chroma, local embeddings, agents,
  verification, guardrails. These tests measure *the system around the model*. A real hosted model adds 1–3 s per call and provider limits (§7), so real end-to-end
  latency is much higher and is **not** load-testable on the available key.
* One 45-second trial per configuration (n = 14–101 completed runs). No repetitions or confidence intervals: small differences (a few percent) are noise.
* Host: one 12-CPU Windows laptop running Docker Desktop (WSL2, 7.4 GB for containers) that was also running an IDE, a sync client and a browser. Results are indicative, not a benchmark of the design.
* SLOs are the frozen ones in `docs/SLO.md` (hash recorded in `meta.json`; unchanged since before the first measurement).
* **Bug found by this exercise and fixed** (§6): with the trace collector unreachable, each worker job waited in an end-of-job flush. The first full run (`loadtest/results/before_tracing_fix/`)
  measured the damage; the figures in §2–5 are from the run after the fix.

## 2. Results (after the fix)

| config | workers | users | throughput (runs/s) | e2e runs | e2e failures | e2e p50 (s) | e2e p95 (s) | submit p95 (ms) | queue wait mean / p95≤ (s) | worker utilisation | worker CPU % |
|---|---|---|---|---|---|---|---|---|---|---|---|
| nominal_1w_0.3rps | 1 | 2 | 0.300 | 18 | 0 | 4.2 | 4.7 | 120 | 1.04 / 5.0 | 0.55 | 8 |
| c1_1w_1u | 1 | 1 | 0.378 | 17 | 0 | 2.6 | 2.7 | 87 | 0.03 / 0.1 | 0.76 | 10 |
| c1_1w_2u | 1 | 2 | 0.467 | 21 | 0 | 4.2 | 4.2 | 120 | 1.74 / 5.0 | 0.89 | 11 |
| c1_1w_4u | 1 | 4 | 0.511 | 23 | 0 | 7.2 | 7.8 | 140 | 4.94 / 10.0 | 0.97 | 12 |
| c1_1w_8u | 1 | 8 | 0.489 | 22 | 0 | 16.0 | 16.0 | 280 | 11.55 / 30.0 | 0.98 | 12 |
| w1_12u | 1 | 12 | 0.467 | 21 | 0 | 23.0 | 25.0 | 430 | 17.38 / 30.0 | 0.99 | 12 |
| w2_12u | 2 | 12 | 0.933 | 42 | 0 | 12.0 | 12.0 | 450 | 8.63 / 30.0 | 0.97 | 25 |
| w3_12u | 3 | 12 | 1.400 | 63 | 0 | 7.9 | 8.4 | 410 | 5.39 / 10.0 | 0.97 | 38 |
| cache_on_1w_4u | 1 | 4 | 0.467 | 21 | 0 | 7.8 | 8.3 | 190 | 5.26 / 10.0 | 0.99 | 12 |
| cache_off_1w_4u | 1 | 4 | 0.467 | 21 | 0 | 8.3 | 8.8 | 260 | 5.52 / 10.0 | 0.95 | 14 |
| faults_errors20_rl10 | 1 | 4 | 0.311 | 14 | 0 | 13.0 | 15.0 | 170 | 8.06 / 30.0 | 0.96 | 12 |
| outage_100pct | 1 | 2 | 3.300 | 99 | 0 | 0.6 | 0.6 | 72 | 0.10 / 0.5 | 0.51 | 14 |

"e2e" = submit → terminal status (Locust polls the run). "e2e failures" = runs that never reached a terminal state in 120 s or ended `failed`.
Queue-wait percentiles are histogram **upper bounds** (buckets 0.1, 0.5, 1, 2, 5, 10, 30, 60 s). Submit p99 was ≤ 450 ms in every configuration; POST failure count was 0 in all 12.
Memory (max sampled): worker 433–454 MB each, API 59–81 MB, Chroma ≈ 24 MB.

## 3. SLO verdicts (frozen targets)

| # | Objective | Measured | Verdict |
|---|---|---|---|
| S1 | Submit success ≥ 99 % | 0 POST failures in all 12 configurations (446 submissions in total) | **Met** |
| S2 | Submit p95 ≤ 300 ms | 72–280 ms with ≤ 8 users; **410–450 ms at 12 users** | **Met up to 8 users, missed at 12** (the API shares the host with 1–3 busy workers) |
| S3 | Processing success ≥ 99 % | 0 failures / 0 non-terminal in every configuration | **Met** |
| S4 | Nominal load (1 worker, 0.3 runs/s): p50 ≤ 6 s, p95 ≤ 12 s | **p50 4.2 s, p95 4.7 s** (18 runs) | **Met** |
| S5 | Queue wait p95 ≤ 3 s at nominal | histogram bound ≤ 5 s; mean 1.04 s; p50 ≤ 0.1 s | **Not demonstrated**: the bucket boundary (5 s) is above 3 s, so the target can be neither confirmed nor refuted |
| S6 | 3 workers ≥ 1.5× the throughput of 1 | 1.400 / 0.467 = **3.0×** | **Met** |
| S7 | LLM outage ⇒ 100 % `escalated/llm_unavailable`, never `failed` or fabricated | 103 escalations, all `llm_unavailable`; 0 `failed`; 102 requests short-circuited by the breaker | **Met** |

## 4. Findings

* **Capacity.** One worker completes ≈ 0.47–0.51 runs/s (service time 1.9–2.2 s per run, dominated by 5 stub LLM calls ≈ 1.5 s). Beyond ≈ 2 concurrent users the queue grows linearly (queue wait mean
  0.03 → 1.7 → 4.9 → 11.5 s for 1/2/4/8 users) while throughput stays flat: a saturated single worker. Worker CPU is only ≈ 12 % of the host, so the limit is **serial LLM latency, not CPU**.
* **Scaling.** Throughput scales near-linearly with workers (0.47 → 0.93 → 1.40 runs/s for 1/2/3), p50 at 12 users falls 23 → 12 → 7.9 s.
* **Cache.** Cache on vs off (4 users): throughput identical (0.467/s), e2e p50 7.8 s vs 8.3 s (≈ 6 % better), worker CPU 12 % vs 14 %, 52 retrieval-cache hits vs 0. With a deterministic stub the same queries
  repeat, so this is the best case for a cache; n = 21 per arm, so treat the difference as small and not statistically established.
* **Faults under load** (20 % stub 5xx + 10 % stub 429): 0 requests lost, 14 runs finished, 35 retries (23 server, 12 rate-limit), 13 escalated for regulatory reasons and **3 of 16 ended `llm_unavailable`** after
  retries were exhausted; throughput fell to 0.311/s and p95 to 15 s. No run failed or produced a determination without evidence.
* **Total outage** (100 % stub 5xx): the circuit breaker opened after 3 failures; later runs fail fast (0.6 s p50), 3.3 runs/s, all escalated `llm_unavailable`.
* **Bottleneck summary:** (1) serial LLM calls per run; (2) a single worker process; (3) at 12 users the submit p95 degrades (host contention). An earlier session (`docs/LOAD_TEST.md`) measured that stock RQ fork mode
  re-loads the embedding model per job (~10 s of ~12 s); the default `simple` mode avoids it. That comparison was **not re-run** here.

## 5. Failure and recovery drills (real container stop/start)

`loadtest/failure_drills.py` → `loadtest/results/failure_drills.json`. **5 / 5 pass after fixes**; the first execution passed 1 / 5 and found four defects (§6).

| Drill | Observed |
|---|---|
| API restart | A finished run and its petition were still readable (SQLite on a volume) |
| Worker stopped | 4 submissions accepted (HTTP 202) and held `queued`; `/readyz` reported `workers: 0` / `no_workers` after **18.8 s**; after restart all 4 drained to `escalated` |
| Chroma stopped | The petition ended `escalated` / **`retrieval_unavailable`**, `NO_DETERMINATION`, 0 citations; after restart the next petition was analysed normally |
| Redis stopped | `POST /v1/petitions` → **503**, `/readyz` → 503 with `redis_down`, `/healthz` stays 200; after restart a new petition was processed normally |
| Worker killed mid-run | 2 of 3 runs finished; the interrupted run was declared `failed` after **277 s** (job timeout + 2 min) – reported as failed, not answered; nothing stayed stuck |

## 6. Defects found by the load and drill work (all fixed and covered by tests)

| # | Symptom | Cause | Fix |
|---|---|---|---|
| 1 | Throughput 0.11–0.17 runs/s, queue wait 8–24 s even when idle | With `OTEL_EXPORTER_OTLP_ENDPOINT` set but the collector down, each job blocked up to 3 s in `force_flush` | No blocking flush in the long-lived worker; back-off in fork mode (`test_unreachable_trace_collector_never_delays_a_job`). Throughput 0.47 runs/s afterwards (4×) |
| 2 | With Redis stopped, `/healthz`, `/readyz` and submit all timed out | Blocking Redis metric calls (2 s timeout each, several per request) ran inside the async event loop | Shared "Redis recently down" window; metrics skipped and off the event loop; fast 503 (`test_api_stays_responsive_while_redis_is_down_and_fails_fast`) |
| 3 | `/readyz` reported 4 workers with none alive | RQ keeps killed workers registered for minutes | Workers use `worker_ttl=60`; readiness counts only workers with a heartbeat ≤ 90 s (`test_readiness_counts_only_workers_with_a_recent_heartbeat`) |
| 4 | Chroma outage during citation verification escalated as `agent_error` | Retrieval results can come from the Redis cache, hiding the outage until the verifier re-reads the live index | The re-read failure maps to `retrieval_unavailable` (`test_chroma_failing_during_citation_verification…`) |
| 5 | A killed worker's run stayed `running` for 10+ minutes | Stale threshold was twice the job timeout | Job timeout + 2 min (277 s measured) |

## 7. Real-provider integration (controlled, not load)

The LLM could not be load-tested: the provider key allows **8,000 tokens/minute and 200,000 tokens/day per model**, and one analysis costs 13k–23k tokens. Measured with real calls (see `docs/EVALUATION_REPORT.md`):
a full run takes ≈ 50–86 s on `qwen/qwen3.8-27b` and 80–165 s on `openai/gpt-oss-120b` (token-limit pacing), i.e. a realistic ceiling of about 10 analyses/day on one model. The 19-scenario real evaluation
consumed that daily quota; a later call returned HTTP 429 (tokens per day, "try again in 7m46s"), which the client now treats as a quota error and escalates immediately instead of waiting.

## 8. Not done

Multi-trial repetition with confidence intervals · load above 12 users or beyond 3 workers · soak test · fork-mode vs simple-mode re-measurement · load against a real provider with a paid tier · Grafana viewed in a browser under load (the dashboard queries were verified through the Prometheus API; see `SYSTEM_TESTING_REPORT.md`).
