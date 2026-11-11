"""Scripted (deterministic) model behaviours for the evaluation harness.

IMPORTANT: results produced with these scripts measure the PIPELINE'S SAFETY MACHINERY (verification, guardrails,
escalation, budgets) given a specified model behaviour. They say NOTHING about the quality of any real LLM.
Real-model quality is measured only with `--mode real`.
"""
from __future__ import annotations

import json
import re
from typing import Callable

from ..llm.client import CircuitOpen, LLMError, LLMResponse

BASE_QUOTE = "minimum attendance of 85 % in each registered course"
COND_QUOTE = "a shortage up to a maximum of 10 % may be condoned by the Vice-Chancellor"
DX_QUOTE = "Attendance below 75 % in a credit or non-credit courses"


def _act(tool, **args):
    return {"tool": tool, "args": args, "reason": "scripted"}


RESEARCH_BOTH = [_act("search_keyword", query="minimum attendance required in each registered course", k=5),
                 _act("search_keyword", query="shortage condoned Vice-Chancellor medical reasons", k=5),
                 _act("finish")]
RESEARCH_LOW = [_act("search_keyword", query="minimum attendance required in each registered course", k=5),
                _act("get_clause", clause_id="25OB23.0"), _act("finish")]
TRIAGE_OK = {"classified_type": "attendance", "confidence": 0.9, "attendance_percentage_in_text": None,
             "medical_grounds_claimed": True, "summary": "asks for consideration of attendance shortage", "flags": []}
NO_ESC = {"required": False, "reason": None, "detail": ""}


def _eid(user: str, clause: str) -> str:
    m = re.search(r"\[(E\d+)\][^\n]*clause " + re.escape(clause) + r" \|", user)
    return m.group(1) if m else "E1"


def _verdict(route, cites, esc=None, position=None, basis="Based on the cited passages."):
    def build(user: str) -> dict:
        return {"route": route, "position": position or "Attendance is below the 85 % minimum; see the cited clauses.",
                "basis": basis,
                "citations": [{"evidence_id": _eid(user, c), "clause_id": c, "quote": q} for c, q in cites],
                "escalation": esc or NO_ESC}
    return build


class ScriptedLLM:
    """role -> list of replies (dict | str | Exception | callable(user)->dict). The last reply repeats."""

    def __init__(self, script: dict):
        self.script, self.calls, self._i = script, [], {}

    def complete(self, role, system, user, timeout):
        self.calls.append(role)
        replies = self.script.get(role)
        if not replies:
            raise AssertionError(f"scripted model was called for role '{role}' but none was expected")
        n = self._i.get(role, 0)
        self._i[role] = n + 1
        r = replies[min(n, len(replies) - 1)]
        if callable(r):
            r = r(user)
        if isinstance(r, Exception):
            raise r
        return LLMResponse(text=r if isinstance(r, str) else json.dumps(r), prompt_tokens=None, completion_tokens=None,
                           model="scripted", latency_s=0.0, provider="scripted")


class Failing:
    def __init__(self, exc: Exception):
        self.exc, self.calls = exc, []

    def complete(self, role, system, user, timeout):
        self.calls.append(role)
        raise self.exc


def _pct(p: dict) -> float:
    return float(p.get("attendance_percentage") or 0)


def build(behaviour: str, petition: dict):
    cond_esc = {"required": True, "reason": "committee_discretion",
                "detail": "Condonation is decided by the Vice-Chancellor on recommendation; a human decides."}
    both = [("25OB10.0(4)", BASE_QUOTE), ("25OB10.0(5)", COND_QUOTE)]
    if behaviour == "ambiguous":
        return ScriptedLLM({"triage": [dict(TRIAGE_OK, confidence=0.4, flags=["petition text is vague"])]})
    if behaviour == "condonation":
        return ScriptedLLM({"triage": [TRIAGE_OK], "research": RESEARCH_BOTH,
                            "verifier": [_verdict("refer-to-committee", both, cond_esc)]})
    if behaviour == "reject_low":
        pos = f"Attendance of {_pct(petition):g} % is below the 85 % minimum and below the 75 % level."
        return ScriptedLLM({"triage": [TRIAGE_OK], "research": RESEARCH_LOW,
                            "verifier": [_verdict("reject", [("25OB10.0(4)", BASE_QUOTE), ("25OB23.0", DX_QUOTE)], position=pos)]})
    if behaviour == "no_evidence":
        return ScriptedLLM({"triage": [TRIAGE_OK], "research": [_act("finish")]})
    if behaviour == "conflict":
        esc = {"required": True, "reason": "conflicting_provisions", "detail": "The retrieved provisions appear to conflict."}
        return ScriptedLLM({"triage": [TRIAGE_OK], "research": RESEARCH_BOTH, "verifier": [_verdict("refer-to-committee", both, esc)]})
    if behaviour == "fabricated_quote":
        fake = [("25OB10.0(5)", "a shortage of up to 25 % shall be automatically condoned by the Dean")]
        return ScriptedLLM({"triage": [TRIAGE_OK], "research": RESEARCH_BOTH, "verifier": [_verdict("reject", fake)]})
    if behaviour == "fabricated_clause":
        def bad(user):
            return {"route": "reject", "position": "Not eligible under the cited clause.", "basis": "see citation",
                    "citations": [{"evidence_id": "E1", "clause_id": "25OB99.9", "quote": BASE_QUOTE}], "escalation": NO_ESC}
        return ScriptedLLM({"triage": [TRIAGE_OK], "research": RESEARCH_BOTH, "verifier": [bad]})
    if behaviour == "final_decision":
        return ScriptedLLM({"triage": [TRIAGE_OK], "research": RESEARCH_BOTH, "verifier": [
            _verdict("refer-to-committee", both, cond_esc, position="The petition is hereby approved and the shortage condoned.")]})
    if behaviour == "grant_on_vc":
        return ScriptedLLM({"triage": [TRIAGE_OK], "research": RESEARCH_BOTH, "verifier": [
            _verdict("grant-under-provision", [("25OB10.0(5)", COND_QUOTE)],
                     position="The shortage may be condoned under the cited provision.")]})
    if behaviour == "text_conflict":
        return ScriptedLLM({"triage": [dict(TRIAGE_OK, attendance_percentage_in_text=60.0)]})
    if behaviour == "type_mismatch":
        return ScriptedLLM({"triage": [dict(TRIAGE_OK, classified_type="re-evaluation")]})
    if behaviour == "invalid_output":
        return ScriptedLLM({"triage": ["this is not json", "still not json"]})
    if behaviour == "provider_outage":
        return Failing(LLMError("LLM provider error (HTTP 503)", "server", True, provider="primary"))
    if behaviour == "breaker_open":
        return Failing(CircuitOpen("LLM unavailable: circuit breaker is open for every configured provider; "
                                   "no reliable reasoning is available, escalating without a determination"))
    if behaviour == "unsupported_triage":     # triage classifies as declared; escalation happens before any retrieval
        return ScriptedLLM({"triage": [dict(TRIAGE_OK, classified_type=petition["petition_type"], medical_grounds_claimed=False)]})
    if behaviour == "no_llm_calls":
        return ScriptedLLM({})
    raise ValueError(behaviour)
