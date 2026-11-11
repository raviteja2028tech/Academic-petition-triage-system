"""Data contract for every external interface (D1). Pydantic is the single source of truth.

Only structural rules are enforced here. No academic rule (attendance minimum,
condonation range...) is encoded as input validation, because those rules belong
to the retrieved regulations, not to the ingestion boundary.
"""
from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PetitionType(str, Enum):
    attendance = "attendance"
    re_evaluation = "re-evaluation"
    re_registration = "re-registration"
    medical_leave = "medical-leave"
    grade_grievance = "grade-grievance"


class ReasonCategory(str, Enum):
    medical = "medical"
    personal = "personal"
    sports_cultural = "sports-cultural"
    other = "other"


class MedicalDocumentation(str, Enum):
    none = "none"
    certificate = "certificate"
    hospital_record = "hospital-record"


class RunStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    escalated = "escalated"
    failed = "failed"


TERMINAL_STATUSES = {RunStatus.completed, RunStatus.escalated, RunStatus.failed}


class PetitionRequest(BaseModel):
    """A synthetic student petition. Real student data must never be submitted."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    student_ref: str = Field(pattern=r"^(SYN-\d{6}|STU\d{7})$", description="Synthetic student id, e.g. SYN-000123 or STU2026001")
    program: str = Field(min_length=2, max_length=60)
    admission_batch: str = Field(pattern=r"^\d{4}-\d{2}$", description="e.g. 2025-26")
    petition_type: PetitionType
    course_code: str = Field(pattern=r"^[A-Za-z0-9]{3,12}$")
    semester: int = Field(ge=1, le=8)
    classes_held: Optional[int] = Field(default=None, ge=1, le=1000)
    classes_attended: Optional[int] = Field(default=None, ge=0, le=1000)
    attendance_percentage: Optional[float] = Field(default=None, ge=0, le=100)
    reason_category: ReasonCategory
    medical_documentation: MedicalDocumentation = MedicalDocumentation.none
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    petition_text: str = Field(min_length=20, max_length=2000)

    @model_validator(mode="after")
    def _cross_field(self) -> "PetitionRequest":
        held, att, pct = self.classes_held, self.classes_attended, self.attendance_percentage
        if (held is None) != (att is None):
            raise ValueError("classes_held and classes_attended must be supplied together")
        if held is not None and att is not None:
            if att > held:
                raise ValueError("classes_attended cannot exceed classes_held")
            if pct is not None and abs(100.0 * att / held - pct) > 0.5:
                raise ValueError("attendance_percentage is inconsistent with classes_attended/classes_held")
        if self.petition_type == PetitionType.attendance and pct is None and held is None:
            raise ValueError("attendance petitions require attendance_percentage or classes_held/classes_attended")
        if self.period_start and self.period_end and self.period_start > self.period_end:
            raise ValueError("period_start must not be after period_end")
        return self


class PetitionAccepted(BaseModel):
    run_id: str
    status: RunStatus
    status_url: str


class FieldError(BaseModel):
    field: str
    rule: str
    message: str


class ValidationErrorResponse(BaseModel):
    detail: str = "validation failed; request quarantined, no run started"
    quarantine_id: int
    errors: list[FieldError]


class RunEvent(BaseModel):
    ts: str
    event: str
    detail: dict[str, Any] = {}


class RunView(BaseModel):
    run_id: str
    status: RunStatus
    created_at: str
    updated_at: str
    petition_type: Optional[str] = None
    student_ref: Optional[str] = None
    mode: str = "placeholder"
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    events: list[RunEvent] = []
    petition: Optional[dict[str, Any]] = None       # the synthetic petition as submitted (for the examiner view)
    examiner_decisions: list[dict[str, Any]] = []   # human decisions, separate from `result` (the AI recommendation)
    documents: list[dict[str, Any]] = []            # supporting documents stored for the examiner


class RunSummary(BaseModel):
    run_id: str
    status: RunStatus
    created_at: str
    petition_type: Optional[str] = None
    student_ref: Optional[str] = None
    examiner_decision: Optional[str] = None
    updated_at: Optional[str] = None
    course_code: Optional[str] = None
    attendance_percentage: Optional[float] = None
    route: Optional[str] = None
    escalation_reason: Optional[str] = None
    llm_models: list[str] = []


class RunList(BaseModel):
    counts: dict[str, int]
    runs: list[RunSummary]
    matched: int = 0          # runs matching ALL filters (the page above may be shorter)


class CorpusStatus(BaseModel):
    ready: bool
    sources_present: list[str]
    index_exists: bool
    chroma_reachable: bool
    parse_ok: Optional[bool] = None
    documents_indexed: int = 0
    chunks_indexed: int = 0
    embedding_tag: Optional[str] = None
    last_ingest_at: Optional[str] = None
    last_attempt_status: Optional[str] = None
    last_attempt_at: Optional[str] = None
    warnings: list[str] = []
    errors: list[str] = []
    verified_passages: dict[str, bool] = {}
    difficult_case: dict[str, Any]
    message: str


class Health(BaseModel):
    status: str
    checks: dict[str, str] = {}


class FeedbackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: int = Field(ge=1, le=5, description="1 (poor) .. 5 (excellent)")
    agrees_with_recommendation: Optional[bool] = None
    comment: Optional[str] = Field(default=None, max_length=500)


class FeedbackAccepted(BaseModel):
    run_id: str
    stored: bool = True


class ExaminerDecision(str, Enum):
    """The HUMAN examiner's own action. Deliberately not the same vocabulary as the AI route."""
    accept = "accept-petition"
    reject = "reject-petition"
    more_info = "request-more-information"


class ExaminerDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    decision: ExaminerDecision
    note: str = Field(min_length=10, max_length=1000, description="The examiner's own reasoning (required)")
    examiner_label: str = Field(min_length=2, max_length=64,
                                description="Self-declared name/initials. NOT authenticated: this system has no login.")


class ExaminerDecisionAccepted(BaseModel):
    run_id: str
    decision_id: int
    stored: bool = True
    note: str = ("Recorded as a human decision, separate from the AI recommendation. "
                 "Self-declared identity; no authentication (attributed to authenticated examiner when signed in).")


class UserRole(str, Enum):
    student = "student"
    examiner = "examiner"


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    user_id: str = Field(min_length=3, max_length=50, description="Student ID or Examiner ID")
    password: str = Field(min_length=6, max_length=128, description="Account password")
    role: Optional[UserRole] = Field(default=None, description="Expected role for portal-specific login")


class UserView(BaseModel):
    user_id: str
    role: UserRole
    name: str
    email: Optional[str] = None
    branch: Optional[str] = None
    semester: Optional[int] = None
    section: Optional[str] = None
    usn: Optional[str] = None
    created_at: Optional[str] = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserView


class LogoutResponse(BaseModel):
    message: str = "Logged out successfully"
    success: bool = True

