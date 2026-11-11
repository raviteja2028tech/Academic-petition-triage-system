"""Deterministic evaluation metrics. Every definition is also in docs/evaluation.md.

Per-run signals come from the persisted run (result + events) and from re-reading the index; nothing here calls an LLM.
Metrics apply only where meaningful (e.g. recall needs gold clauses) and report n so small samples are visible.

context_relevance  retrieved passages that belong to a gold clause or its clause family (same root, e.g. 25OB10.0(*)),
                   divided by retrieved passages. Scenarios with gold clauses and >=1 retrieved passage.
gold_recall        gold clauses retrieved at least once / gold clauses. Scenarios with gold clauses.
groundedness       final citations whose quote is a verbatim (whitespace-normalised) substring of the chunk text
                   RE-READ from the index here, / final citations. Runs with >=1 citation.
faithfulness       per run with a determination: 1 if every citation is grounded AND every percentage stated in
                   position/basis is traceable to cited text or the petition (or a difference/sum of those), else 0.
                   A deterministic PROXY: it cannot judge legal logic.
hallucination_rate runs with a determination that nonetheless contain an ungrounded citation or untraceable figure
                   / runs with a determination.   (Expected 0 by construction; it is a regression tripwire.)
attempted_halluc.  LLM-using runs in which the verifier rejected >=1 model citation, or the numeric guardrail fired,
                   / LLM-using runs.  This is where model hallucination shows up.
route_accuracy     route == expected route, over scenarios that assert a route.
escalation_accuracy escalation.required (and reason, when asserted) == expected, over all scenarios.
task_success       status, route, escalation, 'LLM called or not' all as expected AND every citation grounded AND gold
                   recall == 1 (when gold exists). All scenarios.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from ..guardrails.numeric import numbers, unsupported_numbers
from ..retrieval.chunk import norm_clause_id
from .scenarios import Scenario


def _ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _root(norm: str) -> str:
    return norm.split("(")[0]


def mean(xs: list[float]) -> Optional[float]:
    return round(sum(xs) / len(xs), 4) if xs else None


def score_run(sc: Scenario, run: dict, retriever) -> dict:
    res = run.get("result") or {}
    ev = run.get("events", [])
    esc = res.get("escalation") or {}
    cites = res.get("citations") or []
    reviewed = res.get("evidence_reviewed") or []
    retrieved = [norm_clause_id(e["clause_id"]) for e in reviewed]
    gold = [norm_clause_id(g) for g in sc.gold_clauses]
    llm_calls = sum(1 for e in ev if e["event"] == "llm_call")

    # groundedness: re-read every cited chunk from the index
    grounded_flags = []
    for c in cites:
        chunk = retriever.get_chunk(c["chunk_id"])
        grounded_flags.append(bool(chunk and _ws(c["quote"]) and _ws(c["quote"]) in _ws(chunk.text)))

    has_det = res.get("position") not in (None, "NO_DETERMINATION")
    unsupported: list[float] = []
    if has_det:
        pet = sc.petition
        pnums = [float(pet["attendance_percentage"])] if pet.get("attendance_percentage") is not None else []
        cited_texts = []
        for c in cites:
            chunk = retriever.get_chunk(c["chunk_id"])
            if chunk:
                cited_texts.append(chunk.text)
        unsupported = unsupported_numbers((res.get("position") or "") + " " + (res.get("basis") or ""), cited_texts, pnums)

    rec = {"id": sc.id, "category": sc.category, "status": run["status"], "route": res.get("route"),
           "escalation_required": bool(esc.get("required")), "escalation_reason": esc.get("reason"),
           "retrieved_clauses": sorted(set(retrieved)), "citations": [c["clause_id"] for c in cites],
           "llm_calls": llm_calls, "tool_calls": sum(1 for e in ev if e["event"] == "tool_call"),
           "interpretation_dependent": sc.interpretation_dependent,
           # explanation fields for the report: why it ended this way, what the model concluded, which providers errored
           "escalation_detail": (esc.get("detail") or "")[:400], "position": (res.get("position") or "")[:400],
           "llm_errors": [str(e["detail"].get("error"))[:200] for e in ev
                          if e["event"] == "llm_call" and e["detail"].get("ok") is False][:6],
           "retry_events": sum(1 for e in ev if e["event"] == "llm_retry")}

    exp = sc.expected
    rec["status_ok"] = run["status"] == exp.status
    rec["route_ok"] = None if exp.route is None else res.get("route") == exp.route
    rec["escalation_ok"] = (rec["escalation_required"] == exp.escalation_required and
                            (exp.escalation_reason is None or esc.get("reason") == exp.escalation_reason))
    rec["llm_called_ok"] = (llm_calls > 0) == exp.llm_called
    rec["gold_recall"] = (sum(1 for g in gold if g in retrieved) / len(gold)) if gold else None
    if gold and retrieved:
        gold_roots = {_root(g) for g in gold}
        rec["context_relevance"] = sum(1 for r in retrieved if r in gold or _root(r) in gold_roots) / len(retrieved)
    else:
        rec["context_relevance"] = None
    rec["groundedness"] = (sum(grounded_flags) / len(grounded_flags)) if grounded_flags else None
    rec["faithfulness"] = (1.0 if (all(grounded_flags) and not unsupported) else 0.0) if has_det else None
    rec["hallucinated_output"] = ((not all(grounded_flags)) or bool(unsupported)) if has_det else None
    rec["unsupported_figures"] = unsupported
    verif_fail = any(e["event"] == "verification" and e["detail"].get("failures") for e in ev)
    num_guard = any(e["event"] == "guardrail" and e["detail"].get("stage") == "numeric_claims" for e in ev)
    rec["attempted_hallucination"] = (verif_fail or num_guard) if llm_calls else None
    rec["task_success"] = bool(rec["status_ok"] and rec["route_ok"] in (True, None) and rec["escalation_ok"] and
                               rec["llm_called_ok"] and all(grounded_flags) and
                               (rec["gold_recall"] in (None, 1.0)))
    rec["cost"] = res.get("cost")
    rec["prompt_versions"] = res.get("prompt_versions")
    return rec


def aggregate(recs: list[dict]) -> dict[str, Any]:
    def col(k):
        return [r[k] for r in recs if r.get(k) is not None]

    def rate(k):
        v = col(k)
        return {"value": mean([float(x) for x in v]), "n": len(v)}
    halluc = col("hallucinated_output")
    return {
        "context_relevance": rate("context_relevance"),
        "groundedness": rate("groundedness"),
        "faithfulness": rate("faithfulness"),
        "hallucination_rate": {"value": mean([float(x) for x in halluc]), "n": len(halluc)},
        "attempted_hallucination_rate": rate("attempted_hallucination"),
        "gold_clause_recall": rate("gold_recall"),
        "route_accuracy": rate("route_ok"),
        "escalation_accuracy": {"value": mean([float(r["escalation_ok"]) for r in recs]), "n": len(recs)},
        "task_success_rate": {"value": mean([float(r["task_success"]) for r in recs]), "n": len(recs)},
    }


def by_category(recs: list[dict]) -> dict[str, dict]:
    out = {}
    for cat in sorted({r["category"] for r in recs}):
        rs = [r for r in recs if r["category"] == cat]
        out[cat] = {"n": len(rs), "task_success": mean([float(r["task_success"]) for r in rs]),
                    "escalation_accuracy": mean([float(r["escalation_ok"]) for r in rs])}
    return out
