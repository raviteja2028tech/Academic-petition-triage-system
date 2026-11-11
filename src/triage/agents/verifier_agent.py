"""Agent 3 - Verifier/Adjudicator: judges ONLY the retrieved evidence, verifies every citation against the indexed
text, applies authority-reservation rules, and either returns a Determination, asks for another search, or escalates."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .. import guardrails
from ..guardrails.numeric import unsupported_numbers
from .citations import verify_citations
from .context import AgentContext, dumps
from .runtime_errors import RetrievalUnavailable
from .policy import ATTENDANCE_BASE_PCT, CONDONABLE_FLOOR_PP_PCT, FINAL_DECISION, RESERVED_AUTHORITY
from .state import (Determination, Escalation, EscalationReason, EvidenceBundle, TriageResult, VerifierLLMOutput)

ALLOWED_LLM_REASONS = {EscalationReason.corpus_insufficient, EscalationReason.conflicting_provisions,
                       EscalationReason.committee_discretion}


@dataclass
class Outcome:
    kind: str                                  # "determination" | "retry" | "escalate"
    determination: Optional[Determination] = None
    escalation: Optional[Escalation] = None
    hint: str = ""
    failures: list[dict] = field(default_factory=list)


def _evidence_text(bundle: EvidenceBundle) -> str:
    return "\n\n".join(f"[{p.evidence_id}] {p.doc_name} | {p.chapter} | clause {p.clause_id} | p.{p.page_start}\n{p.text}"
                       for p in bundle.passages)


def _escalate(reason: EscalationReason, detail: str, failures: Optional[list[dict]] = None) -> Outcome:
    return Outcome("escalate", escalation=Escalation(required=True, reason=reason, detail=detail),
                   failures=failures or [])


def run(ctx: AgentContext, petition: dict, triage: TriageResult, bundle: EvidenceBundle,
        attempt: int, hint: str = "") -> Outcome:
    if not bundle.passages:
        ctx.record("verification", ok=False, attempt=attempt, note="no evidence retrieved")
        return _escalate(EscalationReason.corpus_insufficient, "No regulation passages were retrieved for this petition.")
    ctx.budget.use_step("verifier")
    out = ctx.call_json("verifier", VerifierLLMOutput, petition=dumps(petition), triage=triage.model_dump_json(),
                        evidence=_evidence_text(bundle), hint=hint or "(none)")

    if FINAL_DECISION.search(out.position) or FINAL_DECISION.search(out.basis):
        ctx.record("verification", ok=False, attempt=attempt, note="output filter: wording of a final decision")
        return _escalate(EscalationReason.output_blocked,
                         "Model output contained wording of a final decision, which this system may not issue.")

    if ctx.settings.guardrails_enabled:
        bad = guardrails.check_output(out.position, out.basis, out.escalation.detail)
        if bad:
            ctx.record("guardrail", stage="output", blocked=True, findings=bad)
            return _escalate(EscalationReason.output_blocked,
                             "Model output failed automated safety checks (" +
                             ", ".join(sorted({b["check"] for b in bad})) + "); no recommendation is shown.")

    verified, failures = verify_citations(out.citations, ctx.registry, _indexed_text(ctx))
    ctx.record("verification", ok=not failures, attempt=attempt, citations_in=len(out.citations),
               verified=[{"evidence_id": c.evidence_id, "clause_id": c.clause_id, "page": c.page} for c in verified],
               failures=failures)
    esc = out.escalation
    needs_citation = out.route in ("reject", "grant-under-provision")
    if ctx.settings.guardrails_enabled and needs_citation and not failures and verified:
        cited = [ctx.registry.by_id[c.evidence_id]["text"] for c in verified]
        pet_nums = [n for n in (triage.attendance_percentage,) if n is not None]
        bad_nums = unsupported_numbers(out.position + " " + out.basis, cited, pet_nums)
        if bad_nums:
            failures = [{"why": f"the stated figures {bad_nums} do not appear in the cited text or the petition "
                                "(a citation existing does not prove the conclusion)"}]
            ctx.record("guardrail", stage="numeric_claims", blocked=True, unsupported=bad_nums)
    if failures or (needs_citation and not verified):
        if not failures:
            failures = [{"why": f"route '{out.route}' requires at least one verified citation"}]
        why = "; ".join(f.get("why", "") for f in failures)
        if attempt <= ctx.settings.max_verify_retries:
            return Outcome("retry", failures=failures, hint=(
                "Verification failed: " + why + ". Retrieve the exact clause text (get_clause / search_keyword) "
                "and only cite verbatim excerpts of passages you actually have."))
        return _escalate(EscalationReason.verification_failed,
                         "Citations could not be verified against the indexed regulations: " + why, failures)

    cited_text = " ".join(ctx.registry.by_id[c.evidence_id]["text"] for c in verified)
    reserved = bool(RESERVED_AUTHORITY.search(cited_text))
    route, escalation = out.route, esc
    if escalation.required and escalation.reason not in ALLOWED_LLM_REASONS:
        escalation = Escalation(required=True, reason=EscalationReason.corpus_insufficient, detail=escalation.detail)
    if route == "grant-under-provision" and reserved:
        route = "refer-to-committee"
        escalation = Escalation(required=True, reason=EscalationReason.committee_discretion,
                                detail="The cited provision reserves the decision to an authority; a grant cannot be "
                                       "recommended directly. " + escalation.detail)
    pct = triage.attendance_percentage
    if (route == "reject" and pct is not None and CONDONABLE_FLOOR_PP_PCT <= pct < ATTENDANCE_BASE_PCT):
        # A rejection inside (or possibly inside) the band that 25OB10.0(5) reserves to the Vice-Chancellor rests on the
        # model's own reading of documents/grounds and of the unconfirmed "10 %" meaning. A human decides.
        ctx.record("guardrail", stage="reject_in_condonable_band", blocked=True, attendance=pct)
        out = out.model_copy(update={"basis": out.basis + (
            f" [System note: the model proposed 'reject', but {pct:g} % lies between {CONDONABLE_FLOOR_PP_PCT:g} % and "
            f"{ATTENDANCE_BASE_PCT:g} %, where clause 25OB10.0(5) reserves condonation to the Vice-Chancellor and the meaning "
            "of '10 %' is unconfirmed. The system does not recommend a rejection here; a human decides.]")})
        route = "refer-to-committee"
        escalation = Escalation(required=True, reason=EscalationReason.committee_discretion,
                                detail="Attendance is inside the band where condonation is reserved to the Vice-Chancellor; "
                                       "the AI may not recommend rejection. " + escalation.detail)
    if route == "refer-to-committee" and not escalation.required:
        escalation = Escalation(required=True, reason=(EscalationReason.committee_discretion if reserved
                                                      else EscalationReason.corpus_insufficient),
                                detail=escalation.detail or "Referred for human decision.")
    if route != "refer-to-committee" and escalation.required:
        route = "refer-to-committee"           # an escalation always means a human decides
    det = Determination(route=route, position=out.position, basis=out.basis, citations=verified, escalation=escalation)
    return Outcome("determination", determination=det)


def _indexed_text(ctx: AgentContext):
    def get(chunk_id: str) -> Optional[str]:
        try:
            r = ctx.retriever.get_chunk(chunk_id)
        except Exception as e:  # noqa: BLE001  (Chroma unreachable while verifying: cached research results can hide an outage)
            raise RetrievalUnavailable(f"cannot re-read the regulation index to verify citations: {type(e).__name__}") from e
        return r.text if r else None
    return get
