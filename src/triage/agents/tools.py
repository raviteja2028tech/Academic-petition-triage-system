"""Retrieval tools the Research agent chooses to call. Each call is budgeted, time-limited, and logged to run_events."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout
from typing import Callable

from ..guardrails.injection import PASSAGE_PATTERNS, detect_injection
from ..guardrails.tool_args import ToolArgError, validate_tool_args
from ..retrieval.chunk import TOPIC_RULES
from ..retrieval.search import RetrievalResult
from ..observability import span
from ..reliability.metrics import get_metrics
from .budget import Budget
from .context import AgentContext

TOOL_NAMES = ["search_semantic", "search_keyword", "search_hybrid", "get_clause", "get_neighbouring_clauses",
              "get_petition_fields", "finish"]
EXCERPT = 600


class Toolbox:
    def __init__(self, ctx: AgentContext, petition: dict):
        self.ctx, self.petition = ctx, petition
        self._pool = ThreadPoolExecutor(max_workers=2)
        self.calls = 0

    def close(self) -> None:
        self._pool.shutdown(wait=False)

    def _results(self, tool: str, query: str, res: list[RetrievalResult]) -> list[dict]:
        out = []
        for r in res:
            bad = detect_injection(r.text, only=PASSAGE_PATTERNS) if self.ctx.settings.guardrails_enabled else []
            if bad:      # retrieved text is untrusted too: a passage that reads like an instruction to a model is withheld
                self.ctx.record("guardrail", stage="retrieved_passage", blocked=True, clause=r.metadata.get("clause_id"), findings=bad)
                continue
            eid = self.ctx.registry.add(r.chunk_id, r.text, r.metadata, r.strategy, query, r.score)
            m = r.metadata
            out.append({"evidence_id": eid, "clause_id": m["clause_id"], "page": m["page_start"],
                        "score": round(r.score, 3), "text": r.text[:EXCERPT]})
        return out

    def _dispatch(self, tool: str, args: dict) -> tuple[str, list[RetrievalResult] | dict]:
        rt = self.ctx.retriever
        k = max(1, min(int(args.get("k", self.ctx.settings.search_top_k)), 8))
        if tool == "search_semantic":
            topic = args.get("topic")
            where = {f"t_{topic}": True} if topic in TOPIC_RULES else None
            return str(args["query"]), rt.semantic(str(args["query"]), k, where)
        if tool == "search_hybrid":
            topic = args.get("topic")
            where = {f"t_{topic}": True} if topic in TOPIC_RULES else None
            return str(args["query"]), rt.hybrid(str(args["query"]), k, where)
        if tool == "search_keyword":
            return str(args["query"]), rt.keyword(str(args["query"]), k)
        if tool == "get_clause":
            return str(args["clause_id"]), rt.by_clause_id(str(args["clause_id"]))
        if tool == "get_neighbouring_clauses":
            return str(args["clause_id"]), rt.neighbours(str(args["clause_id"]))
        raise KeyError(tool)

    def call(self, tool: str, args: dict) -> dict:
        """Returns {"ok": bool, ...}. Raises BudgetExhausted only for budget conditions."""
        if tool == "get_petition_fields":
            self.ctx.budget.use_tool()
            self.calls += 1
            self.ctx.record("tool_call", agent="research", tool=tool, args={}, ok=True, results=[])
            return {"ok": True, "petition": self.petition}
        if tool not in TOOL_NAMES or tool == "finish":
            self.ctx.record("tool_call", agent="research", tool=tool, args=args, ok=False, error="unknown tool")
            return {"ok": False, "error": f"unknown tool '{tool}'. Allowed: {TOOL_NAMES}"}
        try:
            args = validate_tool_args(tool, args)
        except ToolArgError as e:
            self.ctx.record("tool_call", agent="research", tool=tool, args=args, ok=False,
                            error=f"rejected by argument validation: {e}")
            return {"ok": False, "error": f"bad arguments for {tool}: {e}"}
        self.ctx.budget.use_tool()
        self.calls += 1
        t0 = time.time()
        fut = self._pool.submit(self._dispatch, tool, args)
        m = get_metrics(self.ctx.settings)
        try:
            with span(f"tool.{tool}", tool=tool):
                query, res = fut.result(timeout=self.ctx.settings.tool_timeout_seconds)
        except FutTimeout:
            m.inc("tool_calls_total", tool=tool, ok="timeout")
            self.ctx.record("tool_call", agent="research", tool=tool, args=args, ok=False, error="tool timeout")
            return {"ok": False, "error": "tool timed out"}
        except (KeyError, ValueError, TypeError) as e:
            self.ctx.record("tool_call", agent="research", tool=tool, args=args, ok=False,
                            error=f"bad arguments: {type(e).__name__}: {e}")
            return {"ok": False, "error": f"bad arguments for {tool}: {e}"}
        except Exception as e:  # noqa: BLE001  (Chroma/embedding failure)
            self.ctx.record("tool_call", agent="research", tool=tool, args=args, ok=False,
                            error=f"{type(e).__name__}: {e}")
            return {"ok": False, "error": f"retrieval failed: {type(e).__name__}", "infrastructure": True}
        m.inc("tool_calls_total", tool=tool, ok="true")
        m.observe("tool_seconds", time.time() - t0, tool=tool)
        results = self._results(tool, query, res)
        self.ctx.record("tool_call", agent="research", tool=tool, args=args, ok=True,
                        latency_s=round(time.time() - t0, 3),
                        results=[{"evidence_id": r["evidence_id"], "clause_id": r["clause_id"], "page": r["page"],
                                  "score": r["score"]} for r in results])
        return {"ok": True, "results": results}
