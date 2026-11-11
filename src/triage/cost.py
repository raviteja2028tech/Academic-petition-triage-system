"""Token and cost accounting. Cost is an ESTIMATE: tokens are provider-reported when available (otherwise a
chars/4 approximation, labelled 'estimated') and the price comes only from configuration (PRICE_*_PER_1K); if no price
is configured the cost is reported as unknown, never as zero."""
from __future__ import annotations

from typing import Optional

from .config import Settings


def estimate_tokens(text: str) -> int:
    return max(1, len(text or "") // 4)


def call_cost(prompt_tokens: int, completion_tokens: int, s: Settings) -> Optional[float]:
    if s.price_prompt_per_1k is None or s.price_completion_per_1k is None:
        return None
    return (prompt_tokens * s.price_prompt_per_1k + completion_tokens * s.price_completion_per_1k) / 1000.0


def summarize(usage: dict, s: Settings) -> dict:
    """usage: agent -> {calls, prompt_tokens, completion_tokens, estimated_calls}. Returns the run-level cost block."""
    pt = sum(u["prompt_tokens"] for u in usage.values())
    ct = sum(u["completion_tokens"] for u in usage.values())
    calls = sum(u["calls"] for u in usage.values())
    est = sum(u.get("estimated_calls", 0) for u in usage.values())
    source = "none" if calls == 0 else "reported" if est == 0 else "estimated" if est == calls else "mixed"
    usd = call_cost(pt, ct, s)
    note = ("Token counts are provider-reported." if source == "reported" else
            "Some or all token counts are ESTIMATED (provider did not report usage; chars/4)." if source != "none"
            else "No LLM calls were made.")
    if usd is None and calls:
        note += " No price configured (PRICE_PROMPT_PER_1K / PRICE_COMPLETION_PER_1K): cost unknown."
    return {"llm_calls": calls, "prompt_tokens": pt, "completion_tokens": ct, "token_source": source,
            "estimated_cost_usd": round(usd, 6) if usd is not None else None,
            "pricing": "configured" if usd is not None else "unavailable", "note": note,
            "by_agent": {a: {"calls": u["calls"], "prompt_tokens": u["prompt_tokens"],
                             "completion_tokens": u["completion_tokens"]} for a, u in usage.items()}}
