"""Numeric-claim check: a verified citation proves a quote exists, not that the conclusion follows from it.

A cheap, deterministic partial defence: every percentage the model states in its position/basis must be traceable to
(a) a cited quote, (b) the petition's own attendance figure, or (c) a difference/sum of two such numbers (e.g. the
shortfall "5 percentage points"). Untraceable numbers mean the stated reasoning is not supported by its evidence.
This does NOT check legal logic (e.g. whether 80 % really is inside a condonable band); that stays a human judgement.
"""
from __future__ import annotations

import re
from itertools import combinations

NUM = re.compile(r"(?<![\w.])(\d{1,3}(?:\.\d+)?)\s*(?:%|per\s?cent|percent|percentage points?)", re.I)


def numbers(text: str) -> set[float]:
    return {float(m.group(1)) for m in NUM.finditer(text or "")}


def unsupported_numbers(claim_text: str, cited_texts: list[str], petition_numbers: list[float]) -> list[float]:
    known: set[float] = set(petition_numbers)
    for t in cited_texts:
        known |= {float(x) for x in re.findall(r"(?<![\w.])(\d{1,3}(?:\.\d+)?)\s*%", t)}
        known |= numbers(t)
    derived = set(known)
    for a, b in combinations(sorted(known), 2):
        derived |= {round(abs(a - b), 2), round(a + b, 2)}
    return sorted(n for n in numbers(claim_text) if not any(abs(n - k) < 0.051 for k in derived))
