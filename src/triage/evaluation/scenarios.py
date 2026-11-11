"""Evaluation scenarios: synthetic PETITIONS with expected outcomes and gold clauses.

Rules enforced on load (so the set cannot silently drift into fabrication):
* every gold clause must come from VERIFIED_GOLD, i.e. clauses actually read in the supplied PDF
  (docs/corpus_verification.md V2-V5); nothing else may be used as gold;
* petitions are synthetic (student_ref SYN-######) and validated against the real data contract;
* the regulations themselves are never mocked: scenarios reference the real indexed corpus only.
Expected outcomes are the project team's assumptions about correct behaviour. Where they depend on an interpretation
that is still open (docs/corpus_verification.md) the scenario is flagged `interpretation_dependent`.
"""
from __future__ import annotations

import json
import os
from typing import Optional

from pydantic import BaseModel, Field

from ..contracts import PetitionRequest

VERIFIED_GOLD = {"25OB10.0(4)", "25OB10.0(5)", "25OB10.0(7)", "25OB23.0"}
BEHAVIOURS = {"condonation", "reject_low", "no_evidence", "conflict", "fabricated_quote", "fabricated_clause",
              "final_decision", "grant_on_vc", "text_conflict", "type_mismatch", "provider_outage", "breaker_open",
              "invalid_output", "no_llm_calls", "ambiguous", "unsupported_triage"}
CATEGORIES = {"supported", "missing_evidence", "conflicting_evidence", "unsupported_type", "missing_documentation",
              "fabricated_citation", "prompt_injection", "input_safety", "ambiguous", "provider_failure",
              "output_safety"}


class Expected(BaseModel):
    status: str                               # completed | escalated
    route: Optional[str] = None               # None = not asserted
    escalation_required: bool
    escalation_reason: Optional[str] = None   # None = not asserted
    llm_called: bool = True


class Scenario(BaseModel):
    id: str
    category: str
    description: str
    petition: dict
    llm_behaviour: str
    expected: Expected
    gold_clauses: list[str] = Field(default_factory=list)
    interpretation_dependent: bool = False
    settings_override: dict[str, str] = Field(default_factory=dict)
    notes: str = ""


def load_scenarios(path: str) -> list[Scenario]:
    data = json.load(open(path, encoding="utf8"))
    out = [Scenario(**d) for d in data["scenarios"]]
    ids = [s.id for s in out]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate scenario ids")
    for s in out:
        bad = set(s.gold_clauses) - VERIFIED_GOLD
        if bad:
            raise ValueError(f"{s.id}: gold clauses {sorted(bad)} are not in the verified set {sorted(VERIFIED_GOLD)}")
        if s.llm_behaviour not in BEHAVIOURS:
            raise ValueError(f"{s.id}: unknown llm_behaviour {s.llm_behaviour}")
        if s.category not in CATEGORIES:
            raise ValueError(f"{s.id}: unknown category {s.category}")
        PetitionRequest.model_validate(s.petition)          # must be a valid, synthetic petition
    return out


def default_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", "..", "..", "eval", "scenarios.json"))
