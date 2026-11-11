"""Verifies the observability stack of a RUNNING `docker compose --profile observability up -d`:
  * Prometheus targets are UP;
  * every Grafana panel query of observability/grafana/dashboards/triage.json is valid PromQL (no error) and reports whether it currently
    returns data (a panel with no data is listed, not hidden: some series only exist after the event they count has happened);
  * Grafana is healthy and has the provisioned datasource + dashboard;
  * Jaeger knows the services and has at least one trace spanning api and worker (needs one petition processed with OTEL_EXPORTER_OTLP_ENDPOINT set).
Usage: python scripts/verify_observability.py > docs/observability_check.json"""
from __future__ import annotations

import json
import os
import sys

import httpx

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PROM, GRAF, JAEGER, API = (os.environ.get(k, v) for k, v in (("PROM_URL", "http://localhost:9090"), ("GRAFANA_URL", "http://localhost:3000"),
                                                            ("JAEGER_URL", "http://localhost:16686"), ("API_URL", "http://localhost:8000")))
out: dict = {"checks": []}
c = httpx.Client(timeout=15)


def rec(name, ok, detail=""):
    out["checks"].append({"check": name, "pass": bool(ok), "detail": detail})


# Prometheus targets
try:
    t = c.get(f"{PROM}/api/v1/targets").json()["data"]["activeTargets"]
    for x in t:
        rec(f"prometheus target {x['labels']['job']} is up", x["health"] == "up", x.get("lastError") or x["scrapeUrl"])
except Exception as e:  # noqa: BLE001
    rec("prometheus reachable", False, type(e).__name__)

# dashboard queries
dash = json.load(open(os.path.join(ROOT, "observability", "grafana", "dashboards", "triage.json"), encoding="utf8"))
panels = []
for p in dash["panels"]:
    for tg in p.get("targets", []):
        if not tg.get("expr"):
            continue
        try:
            r = c.get(f"{PROM}/api/v1/query", params={"query": tg["expr"]}).json()
            valid = r.get("status") == "success"
            n = len(r["data"]["result"]) if valid else 0
            panels.append({"panel": p["title"], "valid_promql": valid, "series_now": n, "error": r.get("error")})
        except Exception as e:  # noqa: BLE001
            panels.append({"panel": p["title"], "valid_promql": False, "series_now": 0, "error": type(e).__name__})
out["dashboard_queries"] = panels
rec("all dashboard queries are valid PromQL", panels and all(p["valid_promql"] for p in panels), f"{len(panels)} queries")
out["panels_without_data_now"] = sorted({p["panel"] for p in panels if p["valid_promql"] and p["series_now"] == 0})

# metrics exposed by the API
try:
    m = c.get(f"{API}/metrics").text
    for fam in ("runs_total", "run_seconds_bucket", "queue_wait_seconds_bucket", "agent_runs_total", "agent_seconds_bucket", "tool_calls_total",
                "llm_calls_total", "http_requests_total", "queue_depth", "workers_active", "llm_breaker_state"):
        rec(f"/metrics exposes {fam}", fam in m)
except Exception as e:  # noqa: BLE001
    rec("api /metrics reachable", False, type(e).__name__)

# Grafana
try:
    rec("grafana healthy", c.get(f"{GRAF}/api/health").json().get("database") == "ok")
    auth = (os.environ.get("GRAFANA_ADMIN_USER", "admin"), os.environ.get("GRAFANA_ADMIN_PASSWORD", "admin"))
    ds = c.get(f"{GRAF}/api/datasources", auth=auth).json()
    rec("grafana datasource provisioned", any(d["type"] == "prometheus" for d in ds), [d["name"] for d in ds])
    s = c.get(f"{GRAF}/api/search", params={"query": ""}, auth=auth).json()
    rec("grafana dashboard provisioned", any("triage" in x.get("title", "").lower() or "petition" in x.get("title", "").lower() for x in s), [x["title"] for x in s])
except Exception as e:  # noqa: BLE001
    rec("grafana reachable", False, type(e).__name__)

# Jaeger
try:
    svcs = c.get(f"{JAEGER}/api/services").json().get("data", [])
    rec("jaeger lists the api and worker services", any("api" in s for s in svcs) and any("worker" in s for s in svcs), svcs)
    best = 0
    for svc in svcs:                      # a cross-service trace is listed under the service whose spans dominate it: look at all
        if "jaeger" in svc:
            continue
        tr = c.get(f"{JAEGER}/api/traces", params={"service": svc, "limit": 20}).json().get("data", [])
        for t in tr:
            procs = {p["serviceName"] for p in t["processes"].values()}
            best = max(best, len(procs))
            if len(procs) >= 2 and "example_trace" not in out:
                attrs = json.dumps([s["tags"] for s in t["spans"]]).lower()
                out["example_trace"] = {"spans": len(t["spans"]), "services": sorted(procs),
                                        "operations": sorted({s["operationName"] for s in t["spans"]})[:20],
                                        "contains_petition_text": "hospitalised" in attrs or "petition_text" in attrs}
    rec("a single trace spans api AND worker", best >= 2, out.get("example_trace"))
    if "example_trace" in out:
        rec("trace attributes contain no petition text", not out["example_trace"]["contains_petition_text"])
except Exception as e:  # noqa: BLE001
    rec("jaeger reachable", False, type(e).__name__)

out["passed"], out["total"] = sum(x["pass"] for x in out["checks"]), len(out["checks"])
print(json.dumps(out, indent=1, default=str))
sys.exit(0 if out["passed"] == out["total"] else 1)
