"""Background job executed by the RQ worker.

AGENT_MODE=agents (default): runs the LangGraph agent pipeline (src/triage/agents).
AGENT_MODE=placeholder: the Phase 1 stub, kept only as an explicit opt-in for plumbing tests; it makes no
determination and says so in its result.
"""
from __future__ import annotations

import time
from typing import Optional
from datetime import datetime, timezone

import logging

from .. import db
from ..observability import set_context, span, use_parent
from ..observability.tracing import ensure_tracing, flush_tracing
from ..config import get_settings

log = logging.getLogger("triage.worker")
DISCLAIMER = "Recommendation only. An examination officer decides every petition."


def process_petition(run_id: str, traceparent: Optional[str] = None) -> None:
    """RQ entry point. Records run metrics; any unexpected failure leaves the run 'failed' (never stuck 'running')."""
    from ..reliability.metrics import get_metrics
    s = get_settings()
    m = get_metrics(s)
    run = db.get_run(s.db_path, run_id)
    t0 = time.time()
    if run is not None:
        try:
            created = datetime.fromisoformat(run["created_at"])
            m.observe("queue_wait_seconds", max(0.0, (datetime.now(timezone.utc) - created).total_seconds()))
        except Exception:  # noqa: BLE001
            pass
    ensure_tracing("triage-worker")
    set_context(correlation_id=(run or {}).get("correlation_id") or "", run_id=run_id)
    log.info("job_started", extra={"mode": s.agent_mode})
    try:
        with use_parent(traceparent), span("worker.process_petition", run_id=run_id, mode=s.agent_mode):
            if s.agent_mode == "placeholder":
                _placeholder(run_id)
            else:
                from ..agents.runtime import run_pipeline
                run_pipeline(s, run_id)
    except Exception as exc:  # noqa: BLE001
        cur = db.get_run(s.db_path, run_id)
        if cur and cur["status"] in ("queued", "running"):
            db.set_status(s.db_path, run_id, "failed", error=f"{type(exc).__name__}: {exc}"[:500])
        m.inc("runs_total", status="failed")
        m.observe("run_seconds", time.time() - t0, status="failed")
        raise
    final = db.get_run(s.db_path, run_id)
    status = final["status"] if final else "unknown"
    m.inc("runs_total", status=status)
    m.observe("run_seconds", time.time() - t0, status=status)
    flush_tracing()
    log.info("job_finished", extra={"status": status, "duration_s": round(time.time() - t0, 3)})
    if final and final.get("result"):
        esc = (final["result"].get("escalation") or {})
        if esc.get("required"):
            m.inc("escalations_total", reason=esc.get("reason") or "unknown")
    from ..evaluation.auto import maybe_auto_eval
    maybe_auto_eval(s, run_id)          # sampled LLM-judge scoring; never raises, never alters the run


def _placeholder(run_id: str) -> None:
    s = get_settings()
    run = db.get_run(s.db_path, run_id)
    if run is None:
        raise RuntimeError(f"run {run_id} not found")
    if run["status"] != "queued":
        return  # idempotent: never re-process a run that already started
    db.set_status(s.db_path, run_id, "running", detail={"worker": "placeholder"})
    try:
        time.sleep(max(0.0, s.placeholder_delay_seconds))
        result = {
            "mode": "placeholder",
            "evidence_used": False,
            "route": None,
            "position": "NO_DETERMINATION",
            "citations": [],
            "escalation": {"required": False, "reason": None},
            "message": ("Placeholder processing only. No regulations were retrieved and no agent or model was used. "
                        "This is NOT an eligibility position."),
            "disclaimer": DISCLAIMER,
        }
        db.set_status(s.db_path, run_id, "completed", result=result, detail={"mode": "placeholder"})
    except Exception as exc:  # noqa: BLE001
        db.set_status(s.db_path, run_id, "failed", error=f"{type(exc).__name__}: {exc}")
        raise
