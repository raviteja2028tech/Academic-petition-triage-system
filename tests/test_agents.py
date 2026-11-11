"""Phase 3 tests: LangGraph agents, citation verification, escalation.

All LLM behaviour here is SCRIPTED (deterministic fake). Retrieval runs on the REAL VTU PDF, indexed with the
test-only HashEmbedder into an in-process Chroma, using keyword/clause/neighbour tools (no neural model needed).
These tests prove the machinery; they do NOT prove that a real LLM handles the assignment's difficult case.
"""
import json
import os
import re
import uuid

import chromadb
import pytest

from conftest import valid_payload
from triage import db
from triage.agents import runtime
from triage.agents.budget import Budget, BudgetExhausted
from triage.agents.citations import verify_citations
from triage.agents.context import EvidenceRegistry
from triage.agents.state import CitationIn
from triage.config import Settings
from triage.llm.client import LLMError, LLMNotConfigured, LLMResponse, extract_json
from triage.llm.prompts import PromptError, load_prompt
from triage.retrieval.embed import HashEmbedder
from triage.retrieval.ingest import run_ingest
from triage.retrieval.search import Retriever
from triage.retrieval.store import ChromaStore

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_PDF = os.path.join(ROOT, "corpus", "VTU B.Tech. Regulations 2025.pdf")
BASE_Q = "A student who cannot fulfil 100 % attendance shall be required to secure a minimum attendance of 85 % in each registered course"
BASE_QUOTE = "minimum attendance of 85 % in each registered course"
COND_QUOTE = "a shortage up to a maximum of 10 % may be condoned by the Vice-Chancellor"
DX_QUOTE = "Attendance below 75 % in a credit or non-credit courses"


# ------------------------------------------------------------------ fakes
class FakeLLM:
    """script: role -> list of replies. A reply is a dict/str, an Exception (raised), or callable(user)->dict/str.
    The last reply of a role repeats if the list is exhausted."""

    def __init__(self, script):
        self.script, self.calls, self.i = script, [], {}

    def complete(self, role, system, user, timeout):
        self.calls.append((role, user))
        replies = self.script.get(role)
        assert replies, f"unscripted LLM role {role}"
        n = self.i.get(role, 0)
        self.i[role] = n + 1
        r = replies[min(n, len(replies) - 1)]
        if callable(r):
            r = r(user)
        if isinstance(r, Exception):
            raise r
        return LLMResponse(text=r if isinstance(r, str) else json.dumps(r), prompt_tokens=100, completion_tokens=20,
                           model="fake", latency_s=0.01)

    def count(self, role):
        return sum(1 for r, _ in self.calls if r == role)


def triage_ok(**over):
    d = {"classified_type": "attendance", "confidence": 0.9, "attendance_percentage_in_text": None,
         "medical_grounds_claimed": True, "summary": "asks for condonation", "flags": []}
    d.update(over)
    return d


def act(tool, **args):
    return {"tool": tool, "args": args, "reason": "test"}


def eid(user, clause):
    m = re.search(r"\[(E\d+)\][^\n]*clause " + re.escape(clause) + r" \|", user)
    assert m, f"{clause} not among evidence passed to the verifier"
    return m.group(1)


def verdict(route, citations, esc=None, position="Attendance is below the 85 % minimum; see cited clauses.",
            basis="Based on the cited passages."):
    """citations: list of (clause_id, quote) resolved to evidence ids at call time."""
    def build(user):
        return {"route": route, "position": position, "basis": basis,
                "citations": [{"evidence_id": eid(user, c), "clause_id": c, "quote": q} for c, q in citations],
                "escalation": esc or {"required": False, "reason": None, "detail": ""}}
    return build


DIFFICULT_RESEARCH = [act("search_keyword", query="minimum attendance required in each registered course", k=5),
                      act("search_keyword", query="shortage condoned Vice-Chancellor medical reasons", k=5),
                      act("get_neighbouring_clauses", clause_id="25OB10.0(5)"),
                      act("finish")]


# ------------------------------------------------------------------ fixtures
@pytest.fixture(scope="module")
def retriever():
    os.environ["CHROMA_COLLECTION"] = "a" + uuid.uuid4().hex[:8]
    os.environ["DB_PATH"] = os.path.join(os.environ.get("TEMP", "."), "agents_index_" + uuid.uuid4().hex[:6] + ".sqlite3")
    os.environ["VERIFIED_PASSAGES_FILE"] = ""
    client = chromadb.EphemeralClient()
    s = Settings()
    emb = HashEmbedder()
    m = run_ingest(s, emb, client, [REAL_PDF], record=False)
    assert m["status"] == "success"
    return Retriever(ChromaStore(client, s.chroma_collection, emb.tag), emb)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.sqlite3"))
    monkeypatch.setenv("PROMPTS_DIR", os.path.join(ROOT, "prompts"))
    monkeypatch.setenv("AGENT_MODE", "agents")
    for k in ("MAX_TOOL_CALLS", "MAX_RESEARCH_STEPS", "MAX_RUN_SECONDS", "MAX_VERIFY_RETRIES"):
        monkeypatch.delenv(k, raising=False)
    return tmp_path


@pytest.fixture
def go(env, retriever, monkeypatch):
    def _go(script, petition=None, llm=None, retr=None):
        s = Settings()
        fake = llm or FakeLLM(script)
        monkeypatch.setattr(runtime, "make_llm", lambda st: fake)
        monkeypatch.setattr(runtime, "make_retriever", lambda st: retr or retriever)
        run_id = db.create_run(s.db_path, petition or valid_payload(), None, "corr-1")
        runtime.run_pipeline(s, run_id)
        return db.get_run(s.db_path, run_id), fake
    return _go


def events(run, name):
    return [e for e in run["events"] if e["event"] == name]


def tool_calls(run):
    return events(run, "tool_call")


def happy_script(route="refer-to-committee", esc=None, research=None, citations=None):
    return {"triage": [triage_ok()], "research": research or DIFFICULT_RESEARCH,
            "verifier": [verdict(route, [("25OB10.0(4)", BASE_QUOTE), ("25OB10.0(5)", COND_QUOTE)] if citations is None else citations, esc)]}


# ------------------------------------------------------------------ the three-agent happy path
def test_handoffs_retrieval_of_base_and_modifying_clause_and_verified_citations(go):
    esc = {"required": True, "reason": "committee_discretion", "detail": "Condonation is by the Vice-Chancellor."}
    run, llm = go(happy_script(esc=esc))
    assert run["status"] == "escalated" and run["mode"] == "agents"
    res = run["result"]
    assert res["route"] == "refer-to-committee" and res["escalation"] == {
        "required": True, "reason": "committee_discretion", "detail": "Condonation is by the Vice-Chancellor."}
    clauses = {c["clause_id"]: c for c in res["citations"]}
    assert set(clauses) == {"25OB10.0(4)", "25OB10.0(5)"}                    # base rule AND modifying provision
    base, cond = clauses["25OB10.0(4)"], clauses["25OB10.0(5)"]
    assert base["document"] == "VTU B.Tech. Regulations 2025.pdf" and base["page"] == 18
    assert cond["page"] == 19 and cond["verified"] is True
    assert "85 %" in base["quote"] and "condoned by the Vice-Chancellor" in cond["quote"]
    reviewed = {e["clause_id"] for e in res["evidence_reviewed"]}
    assert {"25OB10.0(4)", "25OB10.0(5)"} <= reviewed
    # events: agent steps, hand-offs, tool calls with retrieval details, prompts, verification
    names = [e["event"] for e in run["events"]]
    assert names[:3] == ["queued", "running", "prompt_versions"] and names[-1] == "escalated"
    assert [e["detail"]["agent"] for e in events(run, "agent_start")] == ["triage", "research", "verifier"]
    assert [(e["detail"]["from_agent"], e["detail"]["to_agent"]) for e in events(run, "handoff")] == [
        ("triage", "research"), ("research", "verifier")]
    tc = tool_calls(run)
    assert [t["detail"]["tool"] for t in tc] == ["search_keyword", "search_keyword", "get_neighbouring_clauses"]
    assert all(t["detail"]["ok"] and "args" in t["detail"] for t in tc)
    assert any(r["clause_id"] == "25OB10.0(5)" for r in tc[1]["detail"]["results"])
    ver = events(run, "verification")[0]["detail"]
    assert ver["ok"] and len(ver["verified"]) == 2
    assert res["prompt_versions"] == {"triage": "triage_v1", "research": "research_v1", "verifier": "verifier_v1"}
    assert res["agent_stats"]["tool_calls"] == 3 and res["usage"]["research"]["calls"] == 4
    assert res["llm_models"] == ["fake"]                                     # the answering model is recorded
    assert "not a final decision" in res["message"] and "examination officer" in res["disclaimer"]


def test_research_agent_chooses_its_tools(go):
    """Different scripted choices -> different recorded tool calls: retrieval is not a fixed stage."""
    r = [act("get_clause", clause_id="25OB10.0"), act("finish")]
    run, _ = go(happy_script(research=r))
    assert [t["detail"]["tool"] for t in tool_calls(run)] == ["get_clause"]
    assert {x["clause_id"] for x in tool_calls(run)[0]["detail"]["results"]} >= {"25OB10.0(4)", "25OB10.0(5)"}
    run2, _ = go(happy_script(research=[act("finish")], citations=[]))   # finishing immediately -> no evidence -> escalation without calling the verifier LLM
    assert run2["result"]["escalation"]["reason"] == "corpus_insufficient" and tool_calls(run2) == []


def test_reject_with_cited_clause_completes(go):
    p = valid_payload(classes_held=100, classes_attended=72, attendance_percentage=72.0)
    s = happy_script(route="reject", citations=[("25OB10.0(4)", BASE_QUOTE), ("25OB23.0", DX_QUOTE)],
                     research=[act("search_keyword", query="minimum attendance required in each registered course"),
                               act("get_clause", clause_id="25OB23.0"), act("finish")])
    run, _ = go(s, petition=p)
    assert run["status"] == "completed" and run["result"]["route"] == "reject"
    assert run["result"]["escalation"]["required"] is False
    assert {c["clause_id"] for c in run["result"]["citations"]} == {"25OB10.0(4)", "25OB23.0"}


@pytest.mark.parametrize("pct,held,att", [(80.0, 100, 80), (84.0, 100, 84), (75.0, 100, 75)])
def test_model_reject_inside_the_condonable_band_is_converted_to_referral(go, pct, held, att):
    """Real-model finding (eval S06/S07): the model rejected 80 % / 84 % petitions. Clause 25OB10.0(5) reserves condonation in
    that band to the Vice-Chancellor, and the '10 %' reading is unconfirmed, so the AI may not recommend a rejection there."""
    p = valid_payload(classes_held=held, classes_attended=att, attendance_percentage=pct)
    run, _ = go(happy_script(route="reject"), petition=p)
    res = run["result"]
    assert run["status"] == "escalated" and res["route"] == "refer-to-committee"
    assert res["escalation"]["reason"] == "committee_discretion"
    assert "System note" in res["basis"] and "proposed 'reject'" in res["basis"]          # the conversion is visible, not silent
    assert any(e["detail"].get("stage") == "reject_in_condonable_band" for e in events(run, "guardrail"))
    assert {c["clause_id"] for c in res["citations"]} == {"25OB10.0(4)", "25OB10.0(5)"}   # citations stay verified


def test_model_reject_below_every_reading_of_the_band_is_still_allowed(go):
    p = valid_payload(classes_held=100, classes_attended=74, attendance_percentage=74.0)
    run, _ = go(happy_script(route="reject"), petition=p)
    assert run["status"] == "completed" and run["result"]["route"] == "reject"


def test_grant_resting_on_authority_reserved_clause_is_downgraded_to_referral(go):
    """25OB10.0(5) says 'may be condoned by the Vice-Chancellor': the system may not recommend a direct grant."""
    run, _ = go(happy_script(route="grant-under-provision"))
    res = run["result"]
    assert run["status"] == "escalated" and res["route"] == "refer-to-committee"
    assert res["escalation"]["reason"] == "committee_discretion"
    assert {c["clause_id"] for c in res["citations"]} == {"25OB10.0(4)", "25OB10.0(5)"}


# ------------------------------------------------------------------ citation verification
def _reg(go_retriever):
    reg = EvidenceRegistry()
    r = go_retriever.by_clause_id("25OB10.0(5)")[0]
    eid_ = reg.add(r.chunk_id, r.text, r.metadata, "clause", "q", 1.0)
    return reg, eid_, r


def test_verify_citations_accepts_exact_and_rejects_everything_else(retriever):
    reg, e, r = _reg(retriever)
    idx = lambda cid: (retriever.get_chunk(cid) or None) and retriever.get_chunk(cid).text
    ok, bad = verify_citations([CitationIn(evidence_id=e, clause_id="25ob10.0(5)", quote="  " + COND_QUOTE.upper() + " ")],
                               reg, idx)
    assert len(ok) == 1 and not bad
    assert ok[0].document == "VTU B.Tech. Regulations 2025.pdf" and ok[0].page == 19 and ok[0].clause_id == "25OB10.0(5)"
    assert ok[0].quote.lower() == COND_QUOTE.lower()
    cases = {
        "fabricated quote": CitationIn(evidence_id=e, quote="a shortage of up to 25 % may be condoned by the Principal"),
        "paraphrase": CitationIn(evidence_id=e, quote="Vice-Chancellor can forgive missing classes"),
        "wrong clause": CitationIn(evidence_id=e, clause_id="25OB10.0(4)", quote=COND_QUOTE),
        "unretrieved evidence": CitationIn(evidence_id="E99", quote=COND_QUOTE),
        "too short": CitationIn(evidence_id=e, quote="condoned by"),
    }
    for name, c in cases.items():
        ok, bad = verify_citations([c], reg, idx)
        assert ok == [] and len(bad) == 1, name
    # passage no longer in (or changed in) the index
    ok, bad = verify_citations([CitationIn(evidence_id=e, quote=COND_QUOTE)], reg, lambda cid: None)
    assert ok == [] and "index" in bad[0]["why"]
    ok, bad = verify_citations([CitationIn(evidence_id=e, quote=COND_QUOTE)], reg, lambda cid: "different text")
    assert ok == []


def test_fabricated_citation_is_never_returned_and_triggers_research_retry_then_escalation(go):
    fake_quote = "a shortage up to a maximum of 25 % may be condoned by the Principal"
    s = happy_script(citations=[("25OB10.0(4)", BASE_QUOTE), ("25OB10.0(5)", fake_quote)])
    run, llm = go(s)
    res = run["result"]
    assert run["status"] == "escalated" and res["escalation"]["reason"] == "verification_failed"
    assert res["citations"] == [] and res["position"] == "NO_DETERMINATION"
    assert fake_quote not in json.dumps(res)
    ver = events(run, "verification")
    assert len(ver) == 3 and not any(v["detail"]["ok"] for v in ver)          # initial + 2 retries, all rejected
    assert len([h for h in events(run, "handoff") if h["detail"]["from_agent"] == "verifier"]) == 2
    assert llm.count("verifier") == 3
    assert "Verification failed" in llm.calls[-1][1]                           # feedback reached the next attempt


def test_verification_failure_followed_by_corrected_answer(go):
    bad = verdict("reject", [("25OB10.0(4)", "minimum attendance of 99 % in every course at all")])
    good = verdict("reject", [("25OB10.0(4)", BASE_QUOTE)])
    s = {"triage": [triage_ok()], "verifier": [bad, good],
         "research": [act("search_keyword", query="minimum attendance required in each registered course"), act("finish"),
                      act("get_clause", clause_id="25OB10.0(4)"), act("finish")]}
    below_band = valid_payload(classes_held=100, classes_attended=72, attendance_percentage=72.0)   # a reject is allowed here
    run, llm = go(s, petition=below_band)
    assert run["status"] == "completed" and run["result"]["route"] == "reject"
    assert [v["detail"]["ok"] for v in events(run, "verification")] == [False, True]
    assert run["result"]["agent_stats"]["verify_attempts"] == 2


def test_reject_without_any_citation_is_not_allowed(go):
    s = happy_script(route="reject", citations=[])
    run, _ = go(s)
    assert run["result"]["escalation"]["reason"] == "verification_failed" and run["result"]["citations"] == []


# ------------------------------------------------------------------ escalation
@pytest.mark.parametrize("ptype", ["re-evaluation", "re-registration", "medical-leave", "grade-grievance"])
def test_unsupported_petition_types_escalate_without_retrieval(go, ptype):
    p = valid_payload(petition_type=ptype, reason_category="other")
    s = {"triage": [triage_ok(classified_type=ptype)]}
    run, llm = go(s, petition=p)
    res = run["result"]
    assert run["status"] == "escalated" and res["escalation"]["reason"] == "unsupported_petition_type"
    assert res["citations"] == [] and res["position"] == "NO_DETERMINATION" and tool_calls(run) == []
    assert llm.count("research") == 0 and llm.count("verifier") == 0


def test_declared_type_contradicting_text_escalates(go):
    run, llm = go({"triage": [triage_ok(classified_type="grade-grievance")]})
    assert run["result"]["escalation"]["reason"] == "petition_inconsistent" and llm.count("research") == 0


def test_text_contradicting_structured_fields_escalates(go):
    run, _ = go({"triage": [triage_ok(attendance_percentage_in_text=60.0)]})   # fields say 80 %
    assert run["result"]["escalation"]["reason"] == "petition_inconsistent"
    assert "60" in run["result"]["escalation"]["detail"]


def test_no_search_results_means_corpus_insufficient_without_calling_verifier(go):
    s = {"triage": [triage_ok()], "research": [act("get_clause", clause_id="99ZZ9.9"), act("finish")]}
    run, llm = go(s)
    assert run["result"]["escalation"]["reason"] == "corpus_insufficient"
    assert llm.count("verifier") == 0 and run["result"]["citations"] == []


def test_model_reported_conflict_is_escalated_with_only_verified_citations(go):
    esc = {"required": True, "reason": "conflicting_provisions", "detail": "two passages disagree"}
    run, _ = go(happy_script(esc=esc, route="refer-to-committee"))
    assert run["status"] == "escalated" and run["result"]["escalation"]["reason"] == "conflicting_provisions"
    assert all(c["verified"] for c in run["result"]["citations"])


def test_model_escalation_reasons_are_restricted_to_what_a_model_may_claim(go):
    run, _ = go(happy_script(esc={"required": True, "reason": "agent_error", "detail": "x"}))   # system-only reason
    assert run["status"] == "escalated" and run["result"]["escalation"]["reason"] == "corpus_insufficient"
    run2, _ = go(happy_script(esc={"required": True, "reason": "vibes", "detail": "x"}))         # not a reason at all
    assert run2["result"]["escalation"]["reason"] == "invalid_agent_output" and run2["result"]["citations"] == []


def test_output_wording_of_a_final_decision_is_blocked(go):
    s = happy_script()
    s["verifier"] = [lambda u: {**verdict("reject", [("25OB10.0(4)", BASE_QUOTE)])(u),
                                "position": "The petition is hereby rejected. This is the final decision."}]
    run, _ = go(s)
    assert run["result"]["escalation"]["reason"] == "output_blocked" and run["result"]["citations"] == []


# ------------------------------------------------------------------ failures and bounds
def test_llm_error_in_research_escalates(go):
    s = {"triage": [triage_ok()], "research": [LLMError("LLM call timed out after 30s")]}
    run, _ = go(s)
    assert run["status"] == "escalated" and run["result"]["escalation"]["reason"] == "llm_unavailable"
    assert run["result"]["citations"] == [] and run["result"]["position"] == "NO_DETERMINATION"
    end = [e for e in events(run, "agent_end") if not e["detail"]["ok"]]
    assert end and end[0]["detail"]["agent"] == "research"


def test_invalid_model_output_is_repaired_once_then_escalated(go):
    s = {"triage": ["not json at all", triage_ok()], "research": DIFFICULT_RESEARCH,
         "verifier": [verdict("refer-to-committee", [("25OB10.0(5)", COND_QUOTE)],
                              {"required": True, "reason": "committee_discretion", "detail": ""})]}
    run, llm = go(s)
    assert llm.count("triage") == 2 and run["status"] == "escalated"           # repaired on the second try
    s2 = {"triage": ["nope", {"classified_type": "banana"}]}
    run2, _ = go(s2)
    assert run2["result"]["escalation"]["reason"] == "invalid_agent_output" and run2["result"]["citations"] == []


def test_agent_exception_is_contained(go):
    s = {"triage": [RuntimeError("boom")]}
    run, _ = go(s)
    assert run["status"] == "escalated" and run["result"]["escalation"]["reason"] == "agent_error"
    assert run["result"]["position"] == "NO_DETERMINATION"


def test_tool_call_budget_exhaustion_stops_research_and_passes_partial_evidence(go, monkeypatch):
    monkeypatch.setenv("MAX_TOOL_CALLS", "2")
    s = {"triage": [triage_ok()], "research": [act("search_keyword", query="attendance condoned")],   # loops forever
         "verifier": [{"route": "refer-to-committee", "position": "Insufficient evidence.", "basis": "partial",
                       "citations": [], "escalation": {"required": True, "reason": "corpus_insufficient", "detail": "partial"}}]}
    run, llm = go(s)
    assert len(tool_calls(run)) == 2 and run["result"]["agent_stats"]["research_stop_reason"] == "tool_calls"
    assert run["result"]["escalation"]["required"] is True


def test_step_budget_exhaustion(go, monkeypatch):
    monkeypatch.setenv("MAX_RESEARCH_STEPS", "3")
    s = {"triage": [triage_ok()], "research": [act("get_petition_fields")],
         "verifier": [lambda u: {"route": "refer-to-committee", "position": "none", "basis": "none", "citations": [],
                                 "escalation": {"required": True, "reason": "corpus_insufficient", "detail": ""}}]}
    run, llm = go(s)
    assert llm.count("research") == 3 and run["result"]["agent_stats"]["research_stop_reason"] == "steps"
    assert run["result"]["escalation"]["reason"] == "corpus_insufficient"       # no evidence at all


def test_wall_clock_budget_exhaustion_escalates(go, monkeypatch):
    monkeypatch.setenv("MAX_RUN_SECONDS", "0")
    run, llm = go({"triage": [triage_ok()]})
    assert run["result"]["escalation"]["reason"] == "budget_exhausted" and llm.count("triage") == 0


def test_budget_unit():
    t = [0.0]
    b = Budget(2, 2, 10, clock=lambda: t[0])
    b.use_step("a"); b.use_step("a")
    with pytest.raises(BudgetExhausted) as e:
        b.use_step("a")
    assert e.value.kind == "steps"
    b.use_tool(); b.use_tool()
    with pytest.raises(BudgetExhausted) as e:
        b.use_tool()
    assert e.value.kind == "tool_calls"
    t[0] = 11
    with pytest.raises(BudgetExhausted) as e:
        b.check_time()
    assert e.value.kind == "time"


def test_retrieval_backend_failure_escalates(go):
    class Broken:
        def keyword(self, *a, **k):
            raise ConnectionError("chroma down")
    s = {"triage": [triage_ok()], "research": [act("search_keyword", query="attendance"), act("finish")]}
    run, _ = go(s, retr=Broken())
    assert run["result"]["escalation"]["reason"] == "retrieval_unavailable" and run["result"]["citations"] == []


def test_unknown_tool_name_is_reported_back_not_executed(go):
    s = {"triage": [triage_ok()], "research": [act("delete_everything"), act("finish")]}
    run, _ = go(s)
    t = tool_calls(run)[0]["detail"]
    assert t["ok"] is False and "unknown tool" in t["error"]


def test_no_llm_configured_is_a_clear_safe_escalation(env, retriever, monkeypatch):
    for k in ("LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(runtime, "make_retriever", lambda st: retriever)
    s = Settings()
    run_id = db.create_run(s.db_path, valid_payload(), None, "c")
    runtime.run_pipeline(s, run_id)
    run = db.get_run(s.db_path, run_id)
    assert run["status"] == "escalated"
    esc = run["result"]["escalation"]
    assert esc["reason"] == "llm_unavailable" and "LLM_BASE_URL" in esc["detail"]
    assert run["result"]["citations"] == [] and run["result"]["position"] == "NO_DETERMINATION"


def test_retriever_unavailable_at_startup_escalates(env, monkeypatch):
    from triage.agents.runtime_errors import RetrievalUnavailable

    def boom(st):
        raise RetrievalUnavailable("index missing")
    monkeypatch.setattr(runtime, "make_llm", lambda st: FakeLLM({}))
    monkeypatch.setattr(runtime, "make_retriever", boom)
    s = Settings()
    run_id = db.create_run(s.db_path, valid_payload(), None, "c")
    runtime.run_pipeline(s, run_id)
    assert db.get_run(s.db_path, run_id)["result"]["escalation"]["reason"] == "retrieval_unavailable"


def test_pipeline_is_idempotent(go, env):
    run, llm = go(happy_script())
    n = len(llm.calls)
    runtime.run_pipeline(Settings(), run["run_id"])           # already terminal -> untouched
    assert len(llm.calls) == n


# ------------------------------------------------------------------ tools / prompts / client helpers
def test_neighbouring_clause_lookup(retriever):
    n = retriever.neighbours("25OB10.0(5)")
    assert [x.metadata["clause_id"] for x in n] == ["25OB10.0(4)", "25OB10.0(6)"]
    assert retriever.neighbours("99ZZ1.0") == []


def test_chunk_reread_from_index(retriever):
    r = retriever.by_clause_id("25OB10.0(4)")[0]
    assert retriever.get_chunk(r.chunk_id).text == r.text and retriever.get_chunk("nope") is None


def test_prompts_are_versioned_files_with_hashes():
    for name in ("triage", "research", "verifier"):
        p = load_prompt(os.path.join(ROOT, "prompts"), name, "v1")
        assert p.id == f"{name}_v1" and len(p.sha256) == 64 and p.system and p.user
    with pytest.raises(PromptError):
        load_prompt(os.path.join(ROOT, "prompts"), "triage", "v99")


def test_extract_json_variants():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Sure! {"a": {"b": 2}} done') == {"a": {"b": 2}}
    with pytest.raises(ValueError):
        extract_json("no object here")


def test_llm_client_requires_configuration(monkeypatch):
    from triage.llm.client import build_client
    with pytest.raises(LLMNotConfigured):
        build_client(Settings(llm_base_url="", llm_model=""))


def test_no_credentials_or_model_ids_in_prompts_or_agent_code():
    import glob
    text = "".join(open(f, encoding="utf8").read() for f in glob.glob(os.path.join(ROOT, "src", "triage", "**", "*.py"), recursive=True)
                   + glob.glob(os.path.join(ROOT, "prompts", "*.yaml")))
    assert not re.search(r"(gpt-|llama|gemini|claude|mixtral|api\.openai|api\.groq)", text, re.I)


# ------------------------------------------------------------------ end to end through API + RQ worker
def test_end_to_end_api_to_worker_to_result(env, retriever, monkeypatch, make_client_agents):
    client, run_worker = make_client_agents
    fake = FakeLLM(happy_script(esc={"required": True, "reason": "committee_discretion", "detail": "VC decides."}))
    monkeypatch.setattr(runtime, "make_llm", lambda st: fake)
    monkeypatch.setattr(runtime, "make_retriever", lambda st: retriever)
    r = client.post("/v1/petitions", json=valid_payload())
    assert r.status_code == 202
    run_id = r.json()["run_id"]
    assert client.get(f"/v1/runs/{run_id}").json()["status"] == "queued"
    run_worker()
    body = client.get(f"/v1/runs/{run_id}").json()
    assert body["status"] == "escalated" and body["mode"] == "agents"
    assert body["result"]["mode"] == "agents" and body["result"]["route"] == "refer-to-committee"
    assert len(body["result"]["citations"]) == 2
    evs = [e["event"] for e in body["events"]]
    assert {"queued", "running", "agent_start", "tool_call", "handoff", "llm_call", "verification", "escalated"} <= set(evs)


@pytest.fixture
def make_client_agents(env, conn):
    from fastapi.testclient import TestClient
    from rq import Queue, SimpleWorker
    from triage.api.main import create_app
    app = create_app(settings_factory=Settings, redis_factory=lambda s: conn,
                     queue_factory=lambda s, c: Queue(s.queue_name, connection=c))

    def run_worker():
        SimpleWorker([Queue("petitions", connection=conn)], connection=conn).work(burst=True)
    return TestClient(app), run_worker


# ------------------------------------------------------------------ real LLM (only if configured)
@pytest.mark.realllm
def test_real_llm_smoke(env, retriever, monkeypatch):
    if not (os.environ.get("LLM_BASE_URL") and os.environ.get("LLM_MODEL")):
        pytest.skip("LLM_BASE_URL / LLM_MODEL not configured")
    monkeypatch.setattr(runtime, "make_retriever", lambda st: retriever)
    s = Settings()
    run_id = db.create_run(s.db_path, valid_payload(), None, "c")
    runtime.run_pipeline(s, run_id)
    run = db.get_run(s.db_path, run_id)
    assert run["status"] in ("completed", "escalated")
    # structural invariants only: every returned citation must carry verified index data
    for c in run["result"]["citations"]:
        assert c["verified"] and c["document"] and c["clause_id"] and c["page"] and c["quote"]


# ------------------------------------------------------------------ hybrid retrieval (semantic + BM25, RRF)
def _r(cid, score=1.0):
    from triage.retrieval.search import RetrievalResult
    return RetrievalResult(chunk_id=cid, text=cid, score=score, strategy="x", metadata={})


def test_rrf_prefers_passages_that_both_retrievers_rank_well():
    from triage.retrieval.search import rrf_fuse
    sem = [_r("a"), _r("b"), _r("c")]
    kw = [_r("c"), _r("b"), _r("d")]
    fused = [r.chunk_id for r in rrf_fuse([sem, kw], 4)]
    assert set(fused[:2]) == {"b", "c"}                     # ranked by both lists beat a (only semantic) and d (only keyword)
    assert set(fused) == {"a", "b", "c", "d"} and all(r.strategy == "hybrid" for r in rrf_fuse([sem, kw], 4))
    assert rrf_fuse([], 3) == [] and [r.chunk_id for r in rrf_fuse([sem], 2)] == ["a", "b"]   # one empty/absent retriever is fine


def test_hybrid_tool_finds_the_base_rule_and_is_allow_listed(go, retriever):
    from triage.guardrails.tool_args import ToolArgError, validate_tool_args
    assert validate_tool_args("search_hybrid", {"query": "minimum attendance", "k": 5, "topic": "attendance"})["k"] == 5
    with pytest.raises(ToolArgError):
        validate_tool_args("search_hybrid", {"query": "x"})                 # too short
    with pytest.raises(ToolArgError):
        validate_tool_args("search_hybrid", {"query": "minimum attendance", "evil": 1})
    hits = retriever.hybrid("minimum attendance required in each registered course", k=5)
    assert "25OB10.0(4)" in [h.metadata["clause_id"] for h in hits]
    s = happy_script(research=[act("search_hybrid", query="minimum attendance required in each registered course", k=5),
                               act("get_neighbouring_clauses", clause_id="25OB10.0(4)"), act("finish")])
    run, _ = go(s)
    tc = tool_calls(run)
    assert tc[0]["detail"]["tool"] == "search_hybrid" and tc[0]["detail"]["ok"]
    assert any(r["clause_id"] == "25OB10.0(4)" for r in tc[0]["detail"]["results"])
