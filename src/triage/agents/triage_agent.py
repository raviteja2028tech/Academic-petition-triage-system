"""Agent 1 - Triage: classify the petition and extract facts. No retrieval, no regulation knowledge, no decisions."""
from __future__ import annotations

import re
from typing import Optional

from .context import AgentContext, dumps
from .policy import SUPPORTED_TYPES, UNSUPPORTED_NOTES
from .state import TriageLLMOutput, TriageResult

TEXT_FIELD_TOLERANCE = 1.0   # percentage points
_OWN_ATTENDANCE = re.compile(r"(?:my\s+attendance|i\s+(?:have|had|attended|got)|attendance\s+(?:is|was|stands|of))[^.\d%]{0,40}?"
                             r"(\d{1,3}(?:\.\d+)?)\s*(?:%|per\s?cent|percent)", re.I)
_RULE_WORDS = re.compile(r"minimum|required|requirement|at least|shortage|condon|below|short of", re.I)


def percentages_in_text(text: str) -> list[float]:
    """Deterministic (non-LLM) extraction of percentages the student states about THEIR OWN attendance, so a contradiction with the
    structured fields does not depend on the model noticing. Phrases about the rule ("minimum attendance of 85 %") are ignored."""
    out = []
    for m in _OWN_ATTENDANCE.finditer(text or ""):
        v = float(m.group(1))
        if v <= 100 and not _RULE_WORDS.search(text[max(0, m.start() - 25):m.end()]):
            out.append(v)
    return out


def structured_attendance(p: dict) -> Optional[float]:
    if p.get("attendance_percentage") is not None:
        return float(p["attendance_percentage"])
    if p.get("classes_held"):
        return round(100.0 * p["classes_attended"] / p["classes_held"], 2)
    return None


def run(ctx: AgentContext, petition: dict) -> TriageResult:
    ctx.budget.use_step("triage")
    out = ctx.call_json("triage", TriageLLMOutput, petition=dumps(petition))
    declared = petition["petition_type"]
    pct = structured_attendance(petition)
    flags = list(out.flags)
    if out.classified_type != declared:
        flags.append(f"declared type '{declared}' differs from classified type '{out.classified_type}'")
    if (out.attendance_percentage_in_text is not None and pct is not None
            and abs(out.attendance_percentage_in_text - pct) > TEXT_FIELD_TOLERANCE):
        flags.append(f"text states {out.attendance_percentage_in_text}% but fields give {pct}%")
    for v in percentages_in_text(petition.get("petition_text", "")):
        msg = f"text states {v:g}% but fields give {pct:g}%" if pct is not None else ""
        if pct is not None and abs(v - pct) > TEXT_FIELD_TOLERANCE and msg not in flags:
            flags.append(msg)
    supported = declared in SUPPORTED_TYPES
    return TriageResult(
        declared_type=declared, classified_type=out.classified_type, confidence=out.confidence,
        attendance_percentage=pct, attendance_percentage_in_text=out.attendance_percentage_in_text,
        medical_grounds_claimed=out.medical_grounds_claimed or petition.get("reason_category") == "medical",
        documentation=petition.get("medical_documentation", "none"), course_code=petition["course_code"],
        summary=out.summary, flags=flags, supported=supported,
        support_note="" if supported else UNSUPPORTED_NOTES.get(declared, UNSUPPORTED_NOTES["other"]))
