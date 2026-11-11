"""Optional LLM-as-judge scoring (SEPARATE from the deterministic metrics, never mixed into them).

Limitations (also in docs/evaluation.md): the judge is an LLM, so scores are non-deterministic and can be lenient or
biased towards fluent text; a judge from the same model family as the system under test tends to over-rate it; the
judge cannot know the law beyond the passages shown, so it cannot catch a wrong-but-grounded conclusion; scores on
28 scenarios are anecdotal, not statistically meaningful. A judge failure never affects petition processing.
"""
from __future__ import annotations

import json
from typing import Optional

from ..llm.client import LLMError, extract_json
from ..llm.prompts import Prompt

KEYS = ("context_relevance", "groundedness", "faithfulness")


def judge_run(llm, prompt: Prompt, petition: dict, result: dict, passages: list[dict], timeout: float = 30.0) -> dict:
    """passages: [{"evidence_id","clause_id","text"}]. Returns {"status":"ok", scores...} or {"status":"error",...}."""
    try:
        answer = {k: result.get(k) for k in ("route", "position", "basis", "escalation")}
        answer["citations"] = [{"clause_id": c["clause_id"], "quote": c["quote"]} for c in result.get("citations", [])]
        user = prompt.render_user(
            petition=json.dumps({k: v for k, v in petition.items() if k != "student_ref"}, ensure_ascii=False),
            passages="\n".join(f"[{p['evidence_id']}] {p['clause_id']}: {p['text'][:600]}" for p in passages) or "(none)",
            answer=json.dumps(answer, ensure_ascii=False))
        r = llm.complete("judge", prompt.system, user, timeout)
        raw = extract_json(r.text)
        out: dict = {"status": "ok", "rationale": str(raw.get("rationale", ""))[:400], "judge_model": r.model}
        for k in KEYS:
            v: Optional[float] = raw.get(k)
            if v is not None:
                out[k] = max(0.0, min(1.0, float(v)))
        return out
    except (LLMError, ValueError, TypeError, KeyError, AttributeError) as e:
        return {"status": "error", "error": f"{type(e).__name__}: {str(e)[:200]}"}
