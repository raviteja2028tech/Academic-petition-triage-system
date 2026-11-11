### main  (SLO sha256 at run time: `9b7460c8651c26ea…`, cpus: 12, git: 5a322cb)

| config | workers | users | throughput (runs/s) | e2e runs | e2e failures | e2e p50 (s) | e2e p95 (s) | submit p95 (ms) | queue wait mean / p95≤ (s) | worker utilisation | worker CPU % (sum of avgs) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| c1_1w_1u | 1 | 1 | 0.356 | 16 | 0 | 2.7 | 2.7 | 100 | 0.045 / 0.1 | 0.705 | 17 |
| c1_1w_2u | 1 | 2 | 0.422 | 19 | 0 | 4.3 | 4.8 | 110 | 1.925 / 5.0 | 0.877 | 12 |
| c1_1w_4u | 1 | 4 | 0.444 | 20 | 0 | 8.4 | 9.5 | 320 | 5.746 / 10.0 | 0.934 | 19 |
| c1_1w_8u | 1 | 8 | 0.422 | 19 | 0 | 18.0 | 18.0 | 370 | 12.568 / 30.0 | 0.941 | 21 |
| w1_12u | 1 | 12 | 0.422 | 19 | 0 | 24.0 | 28.0 | 730 | 17.977 / 30.0 | 0.884 | 20 |
| w2_12u | 2 | 12 | 0.8 | 36 | 0 | 14.0 | 15.0 | 740 | 9.778 / 30.0 | 0.927 | 41 |
| w3_12u | 3 | 12 | 1.267 | 57 | 0 | 8.7 | 9.8 | 720 | 5.901 / 10.0 | 0.934 | 62 |

### bottleneck  (SLO sha256 at run time: `9b7460c8651c26ea…`, cpus: 12, git: 5a322cb)

| config | workers | users | throughput (runs/s) | e2e runs | e2e failures | e2e p50 (s) | e2e p95 (s) | submit p95 (ms) | queue wait mean / p95≤ (s) | worker utilisation | worker CPU % (sum of avgs) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| fork_worker_1w_4u | 1 | 4 | 0.067 | 3 | 0 | 24.0 | 37.0 | 210 | 21.911 / 60.0 | 0.906 | 97 |
| simple_worker_1w_4u | 1 | 4 | 0.422 | 19 | 0 | 8.9 | 9.2 | 230 | 5.856 / 10.0 | 0.956 | 16 |

_Current `docs/SLO.md` sha256: `9b7460c8651c26ea…`_
