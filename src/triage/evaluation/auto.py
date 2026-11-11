"""Sampled automatic evaluation of finished runs with the LLM judge (AUTO_EVAL_SAMPLE_RATE, default 0 = off).

Runs AFTER the run's final status is stored, inside a blanket try/except: a judge failure is recorded in `run_evals`
and logged, and can never change or fail the petition run.
"""
from __future__ import annotations

import logging
import random
from typing import Callable

from .. import db
from ..config import Settings

log = logging.getLogger("triage.autoeval")


def maybe_auto_eval(s: Settings, run_id: str, rand: Callable[[], float] = random.random) -> bool:
    """Returns True if the run was sampled (whether or not the judge succeeded)."""
    if s.auto_eval_sample_rate <= 0 or rand() >= s.auto_eval_sample_rate:
        return False
    try:
        from ..agents import runtime
        from ..llm.prompts import load_prompt
        from .judge import judge_run
        run = db.get_run(s.db_path, run_id)
        res = (run or {}).get("result") or {}
        if not run or res.get("mode") != "agents" or not res.get("evidence_reviewed"):
            return False                      # nothing to judge (e.g. escalated before retrieval)
        retriever = runtime.make_retriever(s)
        passages = []
        for e in res["evidence_reviewed"]:
            ch = retriever.get_chunk(e["chunk_id"])
            if ch:
                passages.append({"evidence_id": e["evidence_id"], "clause_id": e["clause_id"], "text": ch.text})
        out = judge_run(runtime.make_llm(s), load_prompt(s.prompts_dir, "judge", "v1"), run["petition"], res, passages)
        db.save_eval(s.db_path, run_id, out.get("status", "error"), out)
    except Exception as e:  # noqa: BLE001
        log.warning("auto-eval failed for %s: %s", run_id, type(e).__name__)
        try:
            db.save_eval(s.db_path, run_id, "error", {"status": "error", "error": type(e).__name__})
        except Exception:  # noqa: BLE001
            pass
    return True
