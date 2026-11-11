"""Prompt-injection heuristics for UNTRUSTED text (petition text, model output echoing instructions).

Normalises the text first (Unicode NFKC, zero-width characters removed, case-folded, whitespace collapsed, simple
leetspeak digits mapped) so trivial obfuscation does not defeat the patterns. Pattern matching is still easy to evade
with paraphrase, other languages or encoded payloads; treat a negative result as "not flagged", never as "safe".
"""
from __future__ import annotations

import re
import unicodedata

_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿­"), None)
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})

PATTERNS: list[tuple[str, str]] = [
    ("ignore_instructions", r"\b(ignore|disregard|forget|override|bypass|skip)\b.{0,40}\b(previous|prior|above|earlier|all|any|your|the|these)\b.{0,30}\b(instruction|rule|prompt|guideline|polic|directive|constraint)"),
    ("new_instructions", r"\b(new|updated|real|actual|revised)\s+(instruction|system prompt|directive|rule)s?\b"),
    ("role_override", r"\byou\s+are\s+(now|no longer)\b|\bact\s+as\b|\bpretend\s+(to be|you)\b|\bfrom now on\b.{0,40}\byou\b|\broleplay\b"),
    ("prompt_exfiltration", r"\b(reveal|show|print|repeat|output|display|leak|tell me)\b.{0,30}\b(system prompt|your (prompt|instructions|rules)|hidden (prompt|instructions)|initial prompt)"),
    ("force_outcome", r"\b(approve|grant|accept|condone|pass)\b.{0,25}\b(this|my|the)\b.{0,15}\b(petition|request|case)\b.{0,30}\b(regardless|no matter|without|automatically|immediately)\b|\bmark (this|it|the petition) as (approved|granted|accepted|condoned)\b|\boutput (only )?(approved|granted|grant-under-provision)\b"),
    ("fake_authority", r"\b(i am|this is|message from)\b.{0,20}\b(the )?(vice[- ]?chancellor|registrar|dean|examination officer|administrator|developer|system)\b"),
    ("jailbreak_terms", r"\b(jailbreak|developer mode|dan mode|do anything now|sudo mode|god mode)\b"),
    ("delimiter_smuggling", r"</?\s*(system|assistant|petition[_ ]?text|instructions?)\s*>|<\|im_(start|end)\|>|\[/?inst\]|^\s*(system|assistant)\s*:|```\s*(system|json)\b|\bbegin (system|new) (prompt|instructions?)\b"),
    ("tool_manipulation", r"\b(call|invoke|use|run|execute)\b.{0,20}\b(tool|function|command|shell|sql|curl)\b|\bget_clause\b.{0,10}\(|\bsearch_(semantic|keyword)\b"),
    ("skip_safety_steps", r"\b(do not|don't|never|stop)\s+(escalat|refer|verif|cite|flag)\w*"),
    ("schema_hijack", r"\{\s*\"(route|tool|verdict|escalation)\"\s*:"),
]
_COMPILED = [(n, re.compile(p, re.I | re.S | re.M)) for n, p in PATTERNS]

# patterns that are only meaningful as injection attempts in INPUT; in model output, instruction-leak markers differ
_OUTPUT_ONLY = [("leaked_system_prompt", re.compile(r"you are the (triage|research|verifier)|untrusted data|reply with one json", re.I))]


def normalise(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "").translate(_ZERO_WIDTH)
    return re.sub(r"[ \t\r\f\v]+", " ", t).strip()


# Patterns that are meaningful for text RETRIEVED from the corpus (instructions aimed at a model). Narrower than the petition set so that
# ordinary regulation wording is not flagged; verified to produce zero hits on every chunk of the supplied corpus (tests).
PASSAGE_PATTERNS = {"ignore_instructions", "new_instructions", "role_override", "prompt_exfiltration", "force_outcome",
                    "jailbreak_terms", "delimiter_smuggling", "schema_hijack"}


def detect_injection(text: str, output_mode: bool = False, only: "set[str] | None" = None) -> list[str]:
    """Names of matching patterns (empty = nothing flagged)."""
    base = normalise(text)
    variants = [base, base.lower().translate(_LEET)]            # second pass defeats 1gn0re-style obfuscation
    hits: list[str] = []
    if output_mode:
        return [n for n, rx in _OUTPUT_ONLY if rx.search(base)]
    for n, rx in _COMPILED:
        if only is not None and n not in only:
            continue
        if any(rx.search(v) for v in variants) and n not in hits:
            hits.append(n)
    return hits
