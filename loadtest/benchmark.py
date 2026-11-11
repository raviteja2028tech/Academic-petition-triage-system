"""Benchmark orchestrator (host side). Reproduces every number in docs/LOAD_TEST.md.

  python loadtest/benchmark.py --suite all            # ~25-30 minutes
  python loadtest/benchmark.py --suite quick          # one short smoke configuration
  python loadtest/benchmark.py --suite workers        # 1/2/3 workers at saturating concurrency

Per configuration it: (re)starts workers with the requested scale/env, warms up, samples `docker stats`, runs Locust
headless in a container against the real API, then records Locust's CSV, API /metrics deltas (queue wait, run time,
worker busy time) and resource samples as raw JSON under loadtest/results/<timestamp>/. Nothing is invented: a
configuration that fails to run is recorded with its error.
Requires Docker and `docker compose --profile loadtest` images (built on first use).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import statistics
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

import httpx

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
API = "http://localhost:8000"
BUCKET = re.compile(r'^(\w+)_bucket\{(.*)\} ([0-9.eE+-]+)$')


def sh(cmd: list[str], env: dict | None = None, check: bool = True, timeout: int = 900) -> subprocess.CompletedProcess:
    e = {**os.environ, **(env or {})}
    r = subprocess.run(cmd, cwd=ROOT, env=e, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} -> {r.returncode}\n{r.stdout[-800:]}\n{r.stderr[-800:]}")
    return r


def compose(*args: str, env: dict | None = None, **kw) -> subprocess.CompletedProcess:
    return sh(["docker", "compose", "--profile", "loadtest", *args], env, **kw)


def metrics() -> dict[str, float]:
    out = {}
    for line in httpx.get(f"{API}/metrics", timeout=10).text.splitlines():
        if line and not line.startswith("#"):
            k, _, v = line.rpartition(" ")
            try:
                out[k] = float(v)
            except ValueError:
                pass
    return out


def delta(a: dict, b: dict) -> dict:
    return {k: b[k] - a.get(k, 0.0) for k in b}


def family_hist(d: dict, fam: str) -> dict:
    """Sum a histogram family across label sets: {'count','sum','buckets':{le:count}}"""
    count = sum(v for k, v in d.items() if k.split("{")[0] == fam + "_count")
    total = sum(v for k, v in d.items() if k.split("{")[0] == fam + "_sum")
    buckets: dict[str, float] = {}
    for k, v in d.items():
        m = BUCKET.match(f"{k} {v}")
        if m and m.group(1) == fam:
            le = re.search(r'le="([^"]+)"', m.group(2)).group(1)
            buckets[le] = buckets.get(le, 0.0) + v
    return {"count": count, "sum": total, "buckets": buckets}


def quantile_upper_bound(h: dict, q: float):
    """Smallest histogram bucket bound containing the q-th quantile (coarse: buckets are fixed)."""
    if not h["count"]:
        return None
    for le in sorted((b for b in h["buckets"] if b != "+Inf"), key=float):
        if h["buckets"][le] >= q * h["count"]:
            return float(le)
    return float("inf")


class StatsSampler(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.stop, self.samples = threading.Event(), []

    def run(self):
        while not self.stop.is_set():
            r = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{json .}}"], capture_output=True, text=True, encoding="utf-8", errors="replace")
            for line in r.stdout.splitlines():
                try:
                    j = json.loads(line)
                    mem = j["MemUsage"].split("/")[0].strip()
                    val = float(re.match(r"[0-9.]+", mem).group())
                    unit = mem[len(re.match(r"[0-9.]+", mem).group()):]
                    mb = val * {"KiB": 1 / 1024, "MiB": 1, "GiB": 1024, "B": 1 / 1048576}.get(unit, 1)
                    self.samples.append({"t": time.time(), "name": j["Name"], "cpu_pct": float(j["CPUPerc"].strip("%")), "mem_mb": mb})
                except Exception:  # noqa: BLE001
                    pass


def summarise_resources(samples: list[dict]) -> dict:
    out: dict = {}
    for name in sorted({s["name"] for s in samples}):
        rows = [s for s in samples if s["name"] == name]
        out[name] = {"cpu_pct_avg": round(statistics.mean(r["cpu_pct"] for r in rows), 1),
                     "cpu_pct_max": round(max(r["cpu_pct"] for r in rows), 1),
                     "mem_mb_avg": round(statistics.mean(r["mem_mb"] for r in rows), 1),
                     "mem_mb_max": round(max(r["mem_mb"] for r in rows), 1), "samples": len(rows)}
    return out


def read_locust(prefix: str) -> dict:
    rows = {}
    with open(prefix + "_stats.csv", encoding="utf8") as f:
        for r in csv.DictReader(f):
            rows[r["Name"]] = r

    def pick(name):
        r = rows.get(name)
        if not r:
            return None
        return {"requests": int(r["Request Count"]), "failures": int(r["Failure Count"]),
                "p50_ms": float(r["50%"]), "p95_ms": float(r["95%"]), "p99_ms": float(r["99%"]),
                "avg_ms": float(r["Average Response Time"]), "rps": float(r["Requests/s"])}
    return {"submit": pick("POST /v1/petitions"), "poll": pick("GET /v1/runs/[id]"), "e2e": pick("submit->terminal")}


def wait_ready(timeout: int = 240) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if httpx.get(f"{API}/readyz", timeout=3).status_code == 200:
                c = httpx.get(f"{API}/v1/corpus", timeout=3).json()
                if c["ready"]:
                    return
        except Exception:  # noqa: BLE001
            pass
        time.sleep(2)
    raise RuntimeError("stack not ready (api /readyz or corpus)")


def wait_workers(n: int, timeout: int = 120) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        txt = httpx.get(f"{API}/metrics", timeout=5).text
        m = re.search(r"^workers_active (\d+)", txt, re.M)
        if m and int(m.group(1)) >= n:
            return
        time.sleep(2)
    raise RuntimeError(f"{n} workers not registered")


def warm_up(workers: int) -> None:
    """Load the embedding model in every worker before measuring (first job per worker pays model load)."""
    import concurrent.futures as cf
    payload = {"student_ref": "SYN-000001", "program": "Computer Science", "admission_batch": "2025-26",
               "petition_type": "attendance", "course_code": "CS101", "semester": 3, "classes_held": 50, "classes_attended": 40,
               "attendance_percentage": 80.0, "reason_category": "medical", "medical_documentation": "certificate",
               "petition_text": "I was hospitalised for three weeks and request consideration of my attendance shortage."}
    ids = [httpx.post(f"{API}/v1/petitions", json=payload, timeout=10).json()["run_id"] for _ in range(workers * 3)]
    t0 = time.time()
    pending = set(ids)
    while pending and time.time() - t0 < 300:
        for i in list(pending):
            if httpx.get(f"{API}/v1/runs/{i}", timeout=10).json()["status"] in ("completed", "escalated", "failed"):
                pending.discard(i)
        time.sleep(1)


def run_config(cfg: dict, outdir: str) -> dict:
    name = cfg["name"]
    env = {"LLM_BASE_URL": "http://llm-stub:9100/v1", "LLM_MODEL": "stub-model", "LLM_API_KEY": "",
           "RATE_LIMIT_REQUESTS": "1000000", "CACHE_ENABLED": str(cfg.get("cache", True)).lower(),
           "STUB_LATENCY_MS": str(cfg.get("stub_latency_ms", 300)), "STUB_ERROR_RATE": str(cfg.get("stub_error_rate", 0)),
           "STUB_RATE_LIMIT_RATE": str(cfg.get("stub_rate_limit_rate", 0)), "LLM_BACKOFF_BASE_SECONDS": "0.2",
           "RATE_PER_USER": str(cfg.get("rate_per_user", 0)), "E2E_TIMEOUT_S": "120", "MAX_RUN_SECONDS": "100",
           "BREAKER_FAILURE_THRESHOLD": str(cfg.get("breaker_threshold", 5)),
           "WORKER_MODE": cfg.get("worker_mode", "simple")}
    print(f"\n=== {name}: workers={cfg['workers']} users={cfg['users']} cache={cfg.get('cache', True)} ===", flush=True)
    res: dict = {"config": cfg, "started": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    try:
        compose("up", "-d", "--force-recreate", "--scale", f"worker={cfg['workers']}", "redis", "chroma", "api", "worker",
                "llm-stub", env=env)
        wait_ready()
        wait_workers(cfg["workers"])
        # fresh breaker/cache state per configuration; metrics are handled by before/after deltas
        sh(["docker", "compose", "exec", "-T", "redis", "sh", "-c",
            "redis-cli --scan --pattern 'cb:*' | xargs -r redis-cli del; redis-cli --scan --pattern 'rl:*' | xargs -r redis-cli del; "
            "redis-cli --scan --pattern 'ret:*' | xargs -r redis-cli del; redis-cli --scan --pattern 'emb:*' | xargs -r redis-cli del"],
           check=False)
        warm_up(cfg["workers"])
        before = metrics()
        sampler = StatsSampler()
        sampler.start()
        prefix = f"/loadtest/results/{os.path.basename(outdir)}/{name}"
        os.makedirs(os.path.join(outdir), exist_ok=True)
        t0 = time.time()
        r = compose("run", "--rm", "-e", f"RATE_PER_USER={env['RATE_PER_USER']}", "-e", "E2E_TIMEOUT_S=120", "locust",
                    "-f", "/loadtest/locustfile.py", "--host", "http://api:8000", "--headless", "-u", str(cfg["users"]),
                    "-r", str(cfg["users"]), "-t", f"{cfg['duration']}s", "--csv", prefix, "--only-summary",
                    env=env, check=False, timeout=cfg["duration"] + 300)
        wall = time.time() - t0
        # let in-flight runs drain so queue/run histograms are complete
        time.sleep(5)
        sampler.stop.set()
        after = metrics()
        d = delta(before, after)
        qh, rh = family_hist(d, "queue_wait_seconds"), family_hist(d, "run_seconds")
        loc = read_locust(os.path.join(outdir, name))
        e2e = loc["e2e"]
        res.update({
            "locust": loc, "wall_seconds": round(wall, 1), "locust_exit": r.returncode,
            "throughput_runs_per_s": round(e2e["requests"] / cfg["duration"], 3) if e2e else None,
            "queue_wait": {"count": qh["count"], "mean_s": round(qh["sum"] / qh["count"], 3) if qh["count"] else None,
                           "p50_upper_bound_s": quantile_upper_bound(qh, 0.5), "p95_upper_bound_s": quantile_upper_bound(qh, 0.95)},
            "run_time": {"count": rh["count"], "mean_s": round(rh["sum"] / rh["count"], 3) if rh["count"] else None},
            "worker_utilisation": round(rh["sum"] / (cfg["workers"] * (wall + 5)), 3),   # busy seconds / available worker-seconds (window + drain)
            "counters": {k: v for k, v in d.items() if k.split("{")[0] in (
                "runs_total", "llm_retries_total", "llm_fallback_used_total", "llm_breaker_rejected_total", "cache_hits_total",
                "cache_misses_total", "escalations_total", "llm_calls_total", "rate_limited_total") and v},
            "resources": summarise_resources(sampler.samples), "stub": httpx.get("http://localhost:9100/stats", timeout=3).json() if False else None})
    except Exception as e:  # noqa: BLE001
        res["error"] = f"{type(e).__name__}: {e}"[:600]
        print("  FAILED:", res["error"], flush=True)
    res["finished"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    json.dump(res, open(os.path.join(outdir, name + ".json"), "w", encoding="utf8"), indent=1)
    if "error" not in res:
        e = res["locust"]["e2e"]
        print(f"  e2e n={e['requests']} fail={e['failures']} p50={e['p50_ms']:.0f}ms p95={e['p95_ms']:.0f}ms | "
              f"throughput={res['throughput_runs_per_s']}/s util={res['worker_utilisation']}", flush=True)
    return res


def suites(dur: int) -> dict[str, list[dict]]:
    return {
        "quick": [dict(name="quick_1w_2u", workers=1, users=2, duration=20)],
        "concurrency": [dict(name=f"c1_1w_{u}u", workers=1, users=u, duration=dur) for u in (1, 2, 4, 8)],
        "workers": [dict(name=f"w{w}_12u", workers=w, users=12, duration=dur) for w in (1, 2, 3)],
        "cache": [dict(name="cache_on_1w_4u", workers=1, users=4, duration=dur, cache=True),
                  dict(name="cache_off_1w_4u", workers=1, users=4, duration=dur, cache=False)],
        "bottleneck": [dict(name="fork_worker_1w_4u", workers=1, users=4, duration=dur, worker_mode="fork"),
                       dict(name="simple_worker_1w_4u", workers=1, users=4, duration=dur, worker_mode="simple")],
        "nominal": [dict(name="nominal_1w_0.3rps", workers=1, users=2, duration=max(dur, 60), rate_per_user=0.15)],
        "faults": [dict(name="faults_errors20_rl10", workers=1, users=4, duration=dur, stub_error_rate=0.2, stub_rate_limit_rate=0.1),
                   dict(name="outage_100pct", workers=1, users=2, duration=30, stub_error_rate=1.0, breaker_threshold=3)],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--suite", default="all", help="quick|concurrency|workers|cache|nominal|faults|all (comma separated)")
    ap.add_argument("--duration", type=int, default=45, help="seconds per configuration")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    outdir = a.out or os.path.join(ROOT, "loadtest", "results", ts)
    os.makedirs(outdir, exist_ok=True)
    slo = os.path.join(ROOT, "docs", "SLO.md")
    meta = {"slo_sha256": hashlib.sha256(open(slo, "rb").read()).hexdigest(), "started": ts,
            "docker": sh(["docker", "version", "--format", "{{.Server.Version}}"], check=False).stdout.strip(),
            "git_rev": sh(["git", "rev-parse", "--short", "HEAD"], check=False).stdout.strip() or None,
            "cpus": os.cpu_count(), "note": "LLM replaced by loadtest/llm_stub.py; all other components real."}
    json.dump(meta, open(os.path.join(outdir, "meta.json"), "w"), indent=1)
    sets = suites(a.duration)
    wanted = list(sets) if a.suite == "all" else a.suite.split(",")
    if a.suite == "all":
        wanted.remove("quick")
    compose("build", "locust", "api", "worker")
    results = [run_config(c, outdir) for w in wanted for c in sets[w]]
    json.dump(results, open(os.path.join(outdir, "all.json"), "w", encoding="utf8"), indent=1)
    print(f"\nraw results: {outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
