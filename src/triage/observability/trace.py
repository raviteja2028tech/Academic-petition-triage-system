"""Reconstruct a run's execution from its persisted run_events (the system of record), independent of whether
OpenTelemetry was enabled. Returns a timeline, per-agent summaries, retrieval history, retries and outcome."""
from __future__ import annotations

from datetime import datetime
from typing import Any

SAFE_KEYS = ("agent", "tool", "ok", "latency_s", "reason", "route", "provider", "kind", "attempt", "model", "stage",
             "to_agent", "from_agent", "delay_s", "token_source", "stop_reason", "tool_calls", "citations_in")


def _t(ts: str) -> float:
    return datetime.fromisoformat(ts).timestamp()


def build_trace(run: dict) -> dict[str, Any]:
    ev = run["events"]
    t0 = _t(ev[0]["ts"]) if ev else 0.0
    timeline, agents, retrieval, retries, llm_calls = [], {}, [], [], []
    open_agent: dict[str, float] = {}
    for e in ev:
        d, name, at = e["detail"], e["event"], round(_t(e["ts"]) - t0, 3)
        timeline.append({"at_s": at, "event": name, **{k: d[k] for k in SAFE_KEYS if k in d}})
        a = d.get("agent")
        if name == "agent_start" and a:
            open_agent[a] = _t(e["ts"])
            agents.setdefault(a, {"runs": 0, "failures": 0, "seconds": 0.0, "llm_calls": 0, "tool_calls": 0, "retries": 0})
            agents[a]["runs"] += 1
        elif name == "agent_end" and a in open_agent:
            agents[a]["seconds"] = round(agents[a]["seconds"] + _t(e["ts"]) - open_agent.pop(a), 3)
            agents[a]["failures"] += 0 if d.get("ok") else 1
        elif name == "llm_call" and a:
            agents.setdefault(a, {"runs": 0, "failures": 0, "seconds": 0.0, "llm_calls": 0, "tool_calls": 0, "retries": 0})
            agents[a]["llm_calls"] += 1
            llm_calls.append({"at_s": at, "agent": a, "ok": d.get("ok"), "latency_s": d.get("latency_s"), "provider": d.get("provider"),
                              "model": d.get("model"), "prompt_tokens": d.get("prompt_tokens"), "completion_tokens": d.get("completion_tokens"),
                              "prompt": d.get("prompt"), "error": d.get("error")})
        elif name == "tool_call":
            agents.setdefault("research", {"runs": 0, "failures": 0, "seconds": 0.0, "llm_calls": 0, "tool_calls": 0, "retries": 0})["tool_calls"] += 1
            retrieval.append({"at_s": at, "tool": d.get("tool"), "args": d.get("args"), "ok": d.get("ok"), "error": d.get("error"),
                              "latency_s": d.get("latency_s"), "results": d.get("results", [])})
        elif name in ("llm_retry", "llm_fallback", "llm_skipped"):
            retries.append({"at_s": at, "event": name, **{k: d.get(k) for k in ("provider", "attempt", "kind", "delay_s", "reason")}})
    final = ev[-1] if ev else None
    total = round(_t(final["ts"]) - t0, 3) if final else 0.0
    res = run.get("result") or {}
    return {"run_id": run["run_id"], "correlation_id": run.get("correlation_id"), "status": run["status"],
            "total_seconds": total, "event_count": len(ev),
            "outcome": {"route": res.get("route"), "position": res.get("position"),
                        "escalation": (res.get("escalation") or {}).get("reason"),
                        "citations": len(res.get("citations") or [])},
            "agents": agents, "llm_calls": llm_calls, "retrieval_history": retrieval, "retries_and_fallbacks": retries,
            "retry_count": sum(1 for r in retries if r["event"] == "llm_retry"),
            "prompt_versions": res.get("prompt_versions"), "timeline": timeline}
