"""Turn raw benchmark JSON (loadtest/results/<run>/*.json) into Markdown tables. Numbers are copied, never typed.

  python loadtest/report.py loadtest/results/main loadtest/results/bottleneck > loadtest/results/tables.md
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import sys


def load(d: str) -> list[dict]:
    out = []
    for f in sorted(glob.glob(os.path.join(d, "*.json"))):
        if os.path.basename(f) in ("meta.json", "all.json"):
            continue
        j = json.load(open(f, encoding="utf8"))
        j["_file"] = os.path.basename(f)
        out.append(j)
    return out


def ms(v):
    return "-" if v is None else f"{v / 1000:.1f}"


def row(r: dict) -> str:
    c = r["config"]
    if "error" in r:
        return f"| {c['name']} | {c['workers']} | {c['users']} | ERROR: {r['error'][:80]} |"
    e, s = r["locust"]["e2e"], r["locust"]["submit"]
    qw, res = r["queue_wait"], r["resources"]
    cpu = {k.split("-")[-2] if k.count("-") > 1 else k: v["cpu_pct_avg"] for k, v in res.items()}
    wcpu = sum(v["cpu_pct_avg"] for k, v in res.items() if "worker" in k)
    return (f"| {c['name']} | {c['workers']} | {c['users']} | {r['throughput_runs_per_s']} | {e['requests']} | {e['failures']} | "
            f"{ms(e['p50_ms'])} | {ms(e['p95_ms'])} | {s['p95_ms']:.0f} | {qw['mean_s']} / {qw['p95_upper_bound_s']} | "
            f"{r['worker_utilisation']} | {wcpu:.0f} |")


HEAD = ("| config | workers | users | throughput (runs/s) | e2e runs | e2e failures | e2e p50 (s) | e2e p95 (s) | submit p95 (ms) | "
        "queue wait mean / p95≤ (s) | worker utilisation | worker CPU % (sum of avgs) |\n|---|---|---|---|---|---|---|---|---|---|---|---|")


def main() -> None:
    for d in sys.argv[1:]:
        meta = json.load(open(os.path.join(d, "meta.json"))) if os.path.exists(os.path.join(d, "meta.json")) else {}
        print(f"### {os.path.basename(d)}  (SLO sha256 at run time: `{meta.get('slo_sha256', '?')[:16]}…`, cpus: {meta.get('cpus')}, git: {meta.get('git_rev')})\n")
        print(HEAD)
        for r in load(d):
            print(row(r))
        print()
    slo = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "SLO.md")
    print(f"_Current `docs/SLO.md` sha256: `{hashlib.sha256(open(slo, 'rb').read()).hexdigest()[:16]}…`_")


if __name__ == "__main__":
    main()
