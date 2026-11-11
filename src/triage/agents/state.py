"""Typed hand-off objects between agents (Triage -> Research -> Verifier) and the final result."""
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import field_validator, BaseModel, Field


class EscalationReason(str, Enum):
    corpus_insufficient = "corpus_insufficient"
    conflicting_provisions = "conflicting_provisions"
    committee_discretion = "committee_discretion"        # decision reserved to an authority / committee
    unsupported_petition_type = "unsupported_petition_type"
    petition_inconsistent = "petition_inconsistent"      # declared type / text / fields disagree
    verification_failed = "verification_failed"
    budget_exhausted = "budget_exhausted"
    invalid_agent_output = "invalid_agent_output"
    agent_error = "agent_error"
    llm_unavailable = "llm_unavailable"
    retrieval_unavailable = "retrieval_unavailable"
    output_blocked = "output_blocked"
    petition_ambiguous = "petition_ambiguous"            # triage not confident what is being asked; needs clarification
    unsafe_input = "unsafe_input"                        # injection / abusive text flagged by guardrails


class Escalation(BaseModel):
    required: bool = False
    reason: Optional[EscalationReason] = None
    detail: str = ""

    @field_validator("detail", mode="before")
    @classmethod
    def _null_detail_is_empty(cls, v):
        """Real models often emit "detail": null when no escalation is needed; that is not an invalid answer."""
        return "" if v is None else v


Route = Literal["grant-under-provision", "refer-to-committee", "reject"]
PType = Literal["attendance", "re-evaluation", "re-registration", "medical-leave", "grade-grievance", "other"]


# ---- Agent 1: Triage ----
class TriageLLMOutput(BaseModel):
    classified_type: PType
    confidence: float = Field(ge=0, le=1)
    attendance_percentage_in_text: Optional[float] = None
    medical_grounds_claimed: bool = False
    summary: str = ""
    flags: list[str] = []


class TriageResult(BaseModel):
    declared_type: str
    classified_type: PType
    confidence: float
    attendance_percentage: Optional[float]           # from the structured fields, never from free text
    attendance_percentage_in_text: Optional[float] = None
    medical_grounds_claimed: bool = False
    documentation: str = "none"
    course_code: str = ""
    summary: str = ""
    flags: list[str] = []
    supported: bool = False
    support_note: str = ""


# ---- Agent 2: Research ----
class ResearchAction(BaseModel):
    tool: str
    args: dict = {}
    reason: str = ""


class EvidencePassage(BaseModel):
    evidence_id: str
    chunk_id: str
    doc_name: str
    chapter: str
    clause_id: str
    page_start: int
    page_end: int
    text: str
    strategy: str
    query: str = ""
    score: float = 0.0


class EvidenceBundle(BaseModel):
    passages: list[EvidencePassage] = []
    queries: list[dict] = []
    tool_calls: int = 0
    research_steps: int = 0
    stop_reason: str = "finished"        # finished | steps | tool_calls


# ---- Agent 3: Verifier / Adjudicator ----
class CitationIn(BaseModel):
    evidence_id: str
    clause_id: str = ""
    quote: str


class VerifierLLMOutput(BaseModel):
    route: Route
    position: str = Field(min_length=3)
    basis: str = Field(min_length=3)
    citations: list[CitationIn] = []
    escalation: Escalation = Escalation()


class Citation(BaseModel):
    """A citation that has been checked against the indexed text. All fields come from the index, not the model."""
    evidence_id: str
    chunk_id: str
    document: str
    chapter: str
    clause_id: str
    page: int
    quote: str
    verified: bool = True


class Determination(BaseModel):
    route: Route
    position: str
    basis: str
    citations: list[Citation]
    escalation: Escalation
