"""Agent 2 - Research: repeatedly CHOOSES a retrieval tool (LLM-driven loop) to gather the base rule and any
modifying provisions. It gathers evidence only; it never decides or cites."""
from __future__ import annotations

from .budget import BudgetExhausted
from .context import AgentContext, dumps
from .state import EvidenceBundle, EvidencePassage, ResearchAction, TriageResult
from .tools import Toolbox

HISTORY_LIMIT = 12


def _evidence_view(ctx: AgentContext) -> str:
    if not ctx.registry.by_id:
        return "(none yet)"
    return "\n".join(f"{e['evidence_id']} | {e['clause_id']} | p.{e['page_start']} | {e['text'][:350]}"
                     for e in ctx.registry.by_id.values())


def bundle(ctx: AgentContext, queries: list[dict], steps: int, stop_reason: str) -> EvidenceBundle:
    return EvidenceBundle(passages=[EvidencePassage(**e) for e in ctx.registry.by_id.values()], queries=queries,
                          tool_calls=ctx.budget.tool_calls, research_steps=steps, stop_reason=stop_reason)


def run(ctx: AgentContext, petition: dict, triage: TriageResult, hint: str = "",
        prior_queries: list[dict] | None = None) -> EvidenceBundle:
    queries = list(prior_queries or [])
    history: list[dict] = []
    box = Toolbox(ctx, {k: petition[k] for k in petition if k != "petition_text"})
    steps, stop = 0, "finished"
    try:
        while True:
            try:
                ctx.budget.use_step("research")
            except BudgetExhausted as e:
                if e.kind == "time":
                    raise
                stop = "steps"
                break
            steps += 1
            action = ctx.call_json(
                "research", ResearchAction, petition=dumps({k: v for k, v in petition.items()}),
                triage=triage.model_dump_json(), evidence=_evidence_view(ctx), history=dumps(history[-HISTORY_LIMIT:]),
                tool_calls_left=str(ctx.budget.tool_calls_left), hint=hint or "(none)")
            if action.tool == "finish":
                break
            try:
                res = box.call(action.tool, action.args)
            except BudgetExhausted as e:
                if e.kind == "time":
                    raise
                stop = "tool_calls"
                break
            if res.get("infrastructure") and not ctx.registry.by_id:
                from .runtime_errors import RetrievalUnavailable
                raise RetrievalUnavailable(res["error"])
            queries.append({"tool": action.tool, "args": action.args, "reason": action.reason,
                            "ok": res["ok"], "evidence_ids": [r["evidence_id"] for r in res.get("results", [])]})
            history.append({"tool": action.tool, "args": action.args, "ok": res["ok"],
                            "clauses": [r["clause_id"] for r in res.get("results", [])],
                            "error": res.get("error")})
    finally:
        box.close()
    return bundle(ctx, queries, steps, stop)
