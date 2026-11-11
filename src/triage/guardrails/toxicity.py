"""Toxicity BASELINE: a small lexicon + threat patterns. No ML model is used (none is bundled or required).

Documented limits: lexicon matching misses sarcasm, implicit abuse, misspellings beyond simple obfuscation and
non-English text, and may flag quoted language. It is a coarse tripwire that sends the case to a human, nothing more.
A classifier (e.g. a small open toxicity model) would be the next step and is NOT implemented.
"""
from __future__ import annotations

import re

from .injection import _LEET, normalise

ABUSE = ["idiot", "idiots", "stupid", "moron", "morons", "imbecile", "scum", "trash", "useless", "worthless",
         "bastard", "bastards", "shut up", "fuck", "fucking", "shit", "bullshit", "asshole", "crap", "dumb", "loser"]
THREATS = [r"\b(i|we)('ll| will| am going to|'m going to)\b.{0,25}\b(kill|hurt|harm|burn|destroy|beat|attack)\b",
           r"\b(kill|hurt|harm|beat|attack|stab|shoot)\b.{0,15}\b(you|him|her|them|professor|dean|staff|teacher)\b",
           r"\b(bomb|burn down)\b.{0,20}\b(college|campus|office|building)\b"]
_ABUSE_RX = re.compile(r"\b(" + "|".join(re.escape(w) for w in ABUSE) + r")\b", re.I)
_THREAT_RX = [re.compile(p, re.I) for p in THREATS]


def toxicity_findings(text: str) -> list[str]:
    base = normalise(text)
    variants = [base, base.lower().translate(_LEET)]
    out: list[str] = []
    for v in variants:
        for m in _ABUSE_RX.finditer(v):
            tag = "abusive_language"
            if tag not in out:
                out.append(tag)
        for rx in _THREAT_RX:
            if rx.search(v) and "threat" not in out:
                out.append("threat")
    return out
