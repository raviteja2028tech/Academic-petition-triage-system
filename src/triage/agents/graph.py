"""LangGraph orchestration: triage -> research <-> verify -> finalize, with typed hand-offs and bounded loops.

Failure handling: every node converts exceptions into an Escalation (never a confident answer):
LLM error/timeout -> llm_unavailable, invalid model output -> invalid_agent_output, budget -> budget_exhausted,
retrieval backend -> retrieval_unavailable, anything else -> agent_error.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from .. import cost, guardrails
from ..llm.client import LLMError, LLMNotConfigured
from ..observability import span
from ..reliability.metrics import get_metrics
from . import research_agent, triage_agent, verifier_agent
from .budget import BudgetExhausted
from .context import AgentContext, InvalidAgentOutput
from .policy import DISCLAIMER, HUMAN_REVIEW_CHECKLIST, OPEN_QUESTIONS
from .runtime_errors import RetrievalUnavailable
from .state import (Determination, Escalation, EscalationReason, EvidenceBundle, TriageResult)

log = logging.getLogger("triage.graph")


class RunState(TypedDict, total=False):
    petition: dict
    triage: dict
    bundle: dict
    determination: dict
    escalation: dict
    attempt: int
    hint: str
    failures: list
    final: dict


def exception_to_escalation(e: Exception) -> Escalation:
    if isinstance(e, LLMNotConfigured):
        return Escalation(required=True, reason=EscalationReason.llm_unavailable, detail=str(e))
    if isinstance(e, LLMError):
        return Escalation(required=True, reason=EscalationReason.llm_unavailable, detail=f"LLM call failed: {e}")
    if isinstance(e, InvalidAgentOutput):
        return Escalation(required=True, reason=EscalationReason.invalid_agent_output, detail=str(e))
    if isinstance(e, BudgetExhausted):
        return Escalation(required=True, reason=EscalationReason.budget_exhausted, detail=str(e))
    if isinstance(e, RetrievalUnavailable):
        return Escalation(required=True, reason=EscalationReason.retrieval_unavailable, detail=str(e))
    log.exception("unexpected agent error")
    return Escalation(required=True, reason=EscalationReason.agent_error,
                      detail=f"Unexpected {type(e).__name__} in an agent; run stopped without a determination.")


def result_dict(ctx: AgentContext, state: RunState, escalation: Escalation, det: Determination | None) -> dict:
    bundle = EvidenceBundle(**state["bundle"]) if state.get("bundle") else None
    reviewed = [{"evidence_id": p.evidence_id, "chunk_id": p.chunk_id, "clause_id": p.clause_id, "page": p.page_start}
                for p in (bundle.passages if bundle else [])]
    return {
        "mode": "agents",
        "evidence_used": bool(reviewed),
        "route": det.route if det else "refer-to-committee",
        "position": det.position if det else "NO_DETERMINATION",
        "basis": det.basis if det else escalation.detail,
        "citations": [c.model_dump() for c in det.citations] if det else [],
        "escalation": escalation.model_dump(mode="json"),
        "evidence_reviewed": reviewed,
        "triage": state.get("triage"),
        "prompt_versions": {k: p.id for k, p in ctx.prompts.items()},
        "agent_stats": {"steps": dict(ctx.budget.steps), "tool_calls": ctx.budget.tool_calls,
                        "verify_attempts": state.get("attempt", 1),
                        "research_stop_reason": bundle.stop_reason if bundle else None},
        "usage": ctx.usage,
        "llm_models": sorted(ctx.models),
        "cost": cost.summarize(ctx.usage, ctx.settings),
        "open_questions": OPEN_QUESTIONS if any(r["clause_id"].startswith("25OB10.0") for r in reviewed) else [],
        "human_review_checklist": HUMAN_REVIEW_CHECKLIST,
        "human_review_required": True,
        "disclaimer": DISCLAIMER,
        "message": ("Recommendation for an examination officer; not a final decision." if det
                    else "No determination was made; escalated to a human. " + escalation.detail),
    }


def build_graph(ctx: AgentContext):
    def guarded(agent: str, fn: Callable[[RunState], dict]) -> Callable[[RunState], dict]:
        def node(state: RunState) -> dict:
            ctx.record("agent_start", agent=agent)
            t0 = time.time()
            m = get_metrics(ctx.settings)
            with span(f"agent.{agent}", agent=agent, run_id=ctx.run_id):
                try:
                    out = fn(state)
                    ctx.record("agent_end", agent=agent, ok=True)
                    m.inc("agent_runs_total", agent=agent, outcome="ok")
                    m.observe("agent_seconds", time.time() - t0, agent=agent)
                    return out
                except Exception as e:  # noqa: BLE001
                    esc = exception_to_escalation(e)
                    ctx.record("agent_end", agent=agent, ok=False, error=f"{type(e).__name__}: {e}"[:300],
                               escalation=esc.reason.value)
                    m.inc("agent_runs_total", agent=agent, outcome=esc.reason.value)
                    m.observe("agent_seconds", time.time() - t0, agent=agent)
                    return {"escalation": esc.model_dump(mode="json")}
        return node

    def triage_fn(state: RunState) -> dict:
        if ctx.settings.guardrails_enabled:
            findings = guardrails.check_input(state["petition"].get("petition_text", ""))
            if findings:
                ctx.record("guardrail", stage="input", blocked=True, findings=findings)
                kinds = sorted({f["check"] for f in findings})
                return {"escalation": Escalation(
                    required=True, reason=EscalationReason.unsafe_input,
                    detail=("The petition text was flagged by automated safety checks (" + ", ".join(kinds) +
                            "); it was not sent to the model and needs human review. These checks are heuristic "
                            "and can flag legitimate text.")).model_dump(mode="json")}
        t = triage_agent.run(ctx, state["petition"])
        ctx.record("handoff", from_agent="triage", to_agent="research", payload=t.model_dump())
        if not t.supported:
            return {"triage": t.model_dump(), "escalation": Escalation(
                required=True, reason=EscalationReason.unsupported_petition_type,
                detail=f"Petition type '{t.declared_type}' is not supported by the verified corpus. {t.support_note}"
            ).model_dump(mode="json")}
        if t.confidence < ctx.settings.triage_min_confidence:
            return {"triage": t.model_dump(), "escalation": Escalation(
                required=True, reason=EscalationReason.petition_ambiguous,
                detail=(f"Triage confidence {t.confidence:.2f} is below the {ctx.settings.triage_min_confidence:.2f} threshold: the petition is "
                        "ambiguous. Clarification is needed from the student or a human reviewer; no recommendation is made. "
                        + "; ".join(t.flags))).model_dump(mode="json")}
        if t.classified_type != t.declared_type or any("text states" in f for f in t.flags):
            return {"triage": t.model_dump(), "escalation": Escalation(
                required=True, reason=EscalationReason.petition_inconsistent,
                detail="; ".join(t.flags) or "petition inconsistent").model_dump(mode="json")}
        return {"triage": t.model_dump()}

    def research_fn(state: RunState) -> dict:
        b = research_agent.run(ctx, state["petition"], TriageResult(**state["triage"]), state.get("hint", ""),
                               (state.get("bundle") or {}).get("queries"))
        ctx.record("handoff", from_agent="research", to_agent="verifier", evidence=[p.clause_id for p in b.passages],
                   tool_calls=b.tool_calls, stop_reason=b.stop_reason)
        return {"bundle": b.model_dump()}

    def verify_fn(state: RunState) -> dict:
        o = verifier_agent.run(ctx, state["petition"], TriageResult(**state["triage"]),
                               EvidenceBundle(**state["bundle"]), state.get("attempt", 1), state.get("hint", ""))
        if o.kind == "determination":
            return {"determination": o.determination.model_dump(mode="json")}
        if o.kind == "retry":
            ctx.record("handoff", from_agent="verifier", to_agent="research", reason="verification_failed",
                       hint=o.hint, attempt=state.get("attempt", 1))
            return {"attempt": state.get("attempt", 1) + 1, "hint": o.hint, "failures": o.failures}
        return {"escalation": o.escalation.model_dump(mode="json"), "failures": o.failures}

    def finalize(state: RunState) -> dict:
        det = Determination(**state["determination"]) if state.get("determination") else None
        esc = Escalation(**state["escalation"]) if state.get("escalation") else (det.escalation if det else
              Escalation(required=True, reason=EscalationReason.agent_error, detail="no determination produced"))
        if det is None and not esc.required:
            esc = Escalation(required=True, reason=EscalationReason.agent_error, detail="no determination produced")
        res = result_dict(ctx, state, esc, det)
        status = "escalated" if esc.required else "completed"
        if esc.required:
            ctx.record("escalation", reason=esc.reason.value if esc.reason else None, detail=esc.detail)
        return {"final": {"status": status, "result": res}}

    def after_triage(state: RunState) -> str:
        return "finalize" if state.get("escalation") else "research"

    def after_research(state: RunState) -> str:
        return "finalize" if state.get("escalation") else "verify"

    def after_verify(state: RunState) -> str:
        if state.get("determination") or state.get("escalation"):
            return "finalize"
        return "research"

    g = StateGraph(RunState)
    g.add_node("triage", guarded("triage", triage_fn))
    g.add_node("research", guarded("research", research_fn))
    g.add_node("verify", guarded("verifier", verify_fn))
    g.add_node("finalize", finalize)
    g.add_edge(START, "triage")
    g.add_conditional_edges("triage", after_triage, {"research": "research", "finalize": "finalize"})
    g.add_conditional_edges("research", after_research, {"verify": "verify", "finalize": "finalize"})
    g.add_conditional_edges("verify", after_verify, {"research": "research", "finalize": "finalize"})
    g.add_edge("finalize", END)
    return g.compile()
