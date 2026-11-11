"""Phase 5 evaluation-framework tests: scenario integrity, metric definitions, scripted run, judge, auto-eval safety."""
import json
import os

import pytest

from conftest import valid_payload
from test_agents import (COND_QUOTE, FakeLLM, env, go, happy_script, retriever, ROOT)  # noqa: F401
from triage import db
from triage.agents import runtime
from triage.config import Settings
from triage.evaluation import metrics as M
from triage.evaluation import run as ev
from triage.evaluation.auto import maybe_auto_eval
from triage.evaluation.judge import judge_run
from triage.evaluation.scenarios import VERIFIED_GOLD, Scenario, default_path, load_scenarios
from triage.llm.client import LLMError, LLMResponse
from triage.llm.prompts import load_prompt


def test_scenario_set_meets_the_requirements():
    scs = load_scenarios(default_path())
    assert len(scs) >= 20 and len({s.id for s in scs}) == len(scs)
    cats = {s.category for s in scs}
    assert {"supported", "missing_evidence", "conflicting_evidence", "unsupported_type", "missing_documentation",
            "fabricated_citation", "prompt_injection", "ambiguous", "provider_failure"} <= cats
    assert all(s.petition["student_ref"].startswith("SYN-") for s in scs)               # synthetic only
    assert all(set(s.gold_clauses) <= VERIFIED_GOLD for s in scs)                        # no invented gold
    assert all(s.expected.status and s.expected.escalation_required is not None for s in scs)
    assert sum(1 for s in scs if s.gold_clauses) >= 10


def test_invented_gold_clause_is_rejected(tmp_path):
    d = json.load(open(default_path(), encoding="utf8"))
    d["scenarios"][0]["gold_clauses"] = ["25OB99.9"]
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(d))
    with pytest.raises(ValueError, match="not in the verified set"):
        load_scenarios(str(p))


def _sc(**over):
    base = dict(id="x", category="supported", description="d", petition=valid_payload(), llm_behaviour="condonation",
                expected={"status": "escalated", "route": "refer-to-committee", "escalation_required": True,
                          "escalation_reason": "committee_discretion"},
                gold_clauses=["25OB10.0(4)", "25OB10.0(5)"])
    base.update(over)
    return Scenario(**base)


class _Chunk:
    def __init__(self, text):
        self.text = text


class _Retr:
    def __init__(self, texts):
        self.texts = texts

    def get_chunk(self, cid):
        return _Chunk(self.texts[cid]) if cid in self.texts else None


def _run(result, events=()):
    return {"status": "escalated", "result": result, "events": list(events)}


def test_groundedness_is_rechecked_against_the_index_not_trusted():
    res = {"route": "refer-to-committee", "position": "p", "basis": "b",
           "escalation": {"required": True, "reason": "committee_discretion"},
           "citations": [{"chunk_id": "c1", "clause_id": "25OB10.0(5)", "quote": "may be condoned"},
                         {"chunk_id": "c2", "clause_id": "25OB10.0(4)", "quote": "an invented sentence"}],
           "evidence_reviewed": [{"clause_id": "25OB10.0(5)", "chunk_id": "c1"}, {"clause_id": "25OB10.0(4)", "chunk_id": "c2"}]}
    r = M.score_run(_sc(), _run(res), _Retr({"c1": "a shortage may   be condoned by VC", "c2": "other text"}))
    assert r["groundedness"] == 0.5 and r["hallucinated_output"] is True and r["task_success"] is False


def test_numeric_claims_feed_faithfulness_and_hallucination():
    res = {"route": "reject", "position": "72 % is below the 85 % minimum and the 60 % floor", "basis": "b",
           "escalation": {"required": False}, "citations": [{"chunk_id": "c", "clause_id": "25OB10.0(4)", "quote": "minimum attendance of 85 %"}],
           "evidence_reviewed": [{"clause_id": "25OB10.0(4)", "chunk_id": "c"}]}
    sc = _sc(petition=valid_payload(attendance_percentage=72.0, classes_held=100, classes_attended=72),
             expected={"status": "completed", "route": "reject", "escalation_required": False}, gold_clauses=["25OB10.0(4)"])
    r = M.score_run(sc, {"status": "completed", "result": res, "events": []}, _Retr({"c": "minimum attendance of 85 % in each course"}))
    assert r["unsupported_figures"] == [60.0] and r["faithfulness"] == 0.0 and r["hallucinated_output"] is True


def test_recall_relevance_route_and_escalation_definitions():
    res = {"route": "refer-to-committee", "position": "NO_DETERMINATION", "escalation": {"required": True, "reason": "committee_discretion"},
           "citations": [], "evidence_reviewed": [{"clause_id": "25OB10.0 (4)", "chunk_id": "a"}, {"clause_id": "25OB10.0(9)", "chunk_id": "b"},
                                                  {"clause_id": "25OB20.0(1)", "chunk_id": "c"}]}
    r = M.score_run(_sc(), _run(res, [{"event": "llm_call", "detail": {}}]), _Retr({}))
    assert r["gold_recall"] == 0.5                                   # (4) found, (5) not
    assert r["context_relevance"] == pytest.approx(2 / 3)            # (4) and same-family (9) relevant, 20.0(1) not
    assert r["route_ok"] is True and r["escalation_ok"] is True and r["task_success"] is False   # recall < 1
    assert r["faithfulness"] is None and r["groundedness"] is None   # no determination -> not applicable


def test_aggregate_reports_n_and_none_for_empty_metrics():
    agg = M.aggregate([{"task_success": True, "escalation_ok": True, "route_ok": True}])
    assert agg["task_success_rate"] == {"value": 1.0, "n": 1}
    assert agg["groundedness"] == {"value": None, "n": 0}


def test_scripted_evaluation_runs_end_to_end_and_flags_a_wrong_expectation(env, retriever, tmp_path):  # noqa: F811
    scs = load_scenarios(default_path())
    recs, j = ev.run_scenarios(scs, "scripted", retriever, str(tmp_path), progress=lambda *_: None)
    assert len(recs) == len(scs) and all(r["task_success"] for r in recs), [r["id"] for r in recs if not r["task_success"]]
    rep = ev.build_report(scs, recs, "scripted", "hash", "v1", j, str(tmp_path))
    assert rep["metrics"]["hallucination_rate"]["value"] == 0.0 and rep["metrics"]["gold_clause_recall"]["value"] == 1.0
    assert rep["metrics"]["attempted_hallucination_rate"]["value"] > 0               # fabricated-citation scenarios were caught
    assert "NOT a measure of any LLM" in rep["meta"]["interpretation"] and j == {"enabled": False}
    md = ev.to_markdown(rep)
    assert "## Deterministic metrics" in md and "Not run" in md
    wrong = [s.model_copy(update={"expected": s.expected.model_copy(update={"escalation_reason": "corpus_insufficient"})})
             for s in scs if s.id.startswith("S01")]
    bad, _ = ev.run_scenarios(wrong, "scripted", retriever, str(tmp_path), progress=lambda *_: None)
    assert bad[0]["task_success"] is False                                            # harness can fail


def test_prompt_variants_exist_and_compare_marks_scripted_runs(tmp_path):
    for n, v in [("research", "v1"), ("research", "v2"), ("judge", "v1"), ("triage", "v1"), ("verifier", "v1")]:
        assert load_prompt(os.path.join(ROOT, "prompts"), n, v).id == f"{n}_{v}"
    assert load_prompt(os.path.join(ROOT, "prompts"), "research", "v1").sha256 != load_prompt(os.path.join(ROOT, "prompts"), "research", "v2").sha256
    a = {"meta": {"research_prompt_version": "v1", "mode": "scripted", "scenario_count": 1},
         "metrics": {"task_success_rate": {"value": 1.0, "n": 1}}, "scenarios": [{"id": "s", "task_success": True}]}
    b = json.loads(json.dumps(a)); b["meta"]["research_prompt_version"] = "v2"; b["metrics"]["task_success_rate"]["value"] = 0.0
    b["scenarios"][0]["task_success"] = False
    pa, pb = tmp_path / "a.json", tmp_path / "b.json"
    pa.write_text(json.dumps(a)); pb.write_text(json.dumps(b))
    out = ev.compare(str(pa), str(pb))
    assert "-1.000" in out and "SCRIPTED" in out and "not statistically meaningful" in out


def test_real_mode_refuses_without_llm_and_fabricates_nothing(monkeypatch, tmp_path, capsys):
    for k in ("LLM_BASE_URL", "LLM_MODEL"):
        monkeypatch.delenv(k, raising=False)
    out = tmp_path / "r.json"
    assert ev.main(["--mode", "real", "--out", str(out)]) == 2
    assert not out.exists() and "no results were fabricated" in capsys.readouterr().err


# ---- judge and sampled auto-eval
class _Judge:
    def __init__(self, reply):
        self.reply = reply

    def complete(self, role, system, user, timeout):
        if isinstance(self.reply, Exception):
            raise self.reply
        return LLMResponse(text=self.reply, model="judge-model")


def test_judge_scores_are_clamped_and_failures_are_contained():
    p = load_prompt(os.path.join(ROOT, "prompts"), "judge", "v1")
    res = {"route": "refer-to-committee", "citations": [{"clause_id": "c", "quote": "q"}]}
    ok = judge_run(_Judge('{"context_relevance": 1.7, "groundedness": 0.5, "faithfulness": null, "rationale": "r"}'), p, valid_payload(), res, [])
    assert ok["status"] == "ok" and ok["context_relevance"] == 1.0 and "faithfulness" not in ok
    assert judge_run(_Judge("not json"), p, valid_payload(), res, [])["status"] == "error"
    assert judge_run(_Judge(LLMError("down")), p, valid_payload(), res, [])["status"] == "error"


def test_auto_eval_is_sampled_stored_and_cannot_disturb_a_run(go, env, retriever, monkeypatch):  # noqa: F811
    run, _ = go(happy_script(esc={"required": True, "reason": "committee_discretion", "detail": "VC"}))
    s = Settings()
    assert maybe_auto_eval(s, run["run_id"]) is False                                 # rate 0 = off
    monkeypatch.setenv("AUTO_EVAL_SAMPLE_RATE", "1")
    s = Settings()
    monkeypatch.setattr(runtime, "make_retriever", lambda st: retriever)
    monkeypatch.setattr(runtime, "make_llm", lambda st: _Judge('{"context_relevance":0.8,"groundedness":1,"faithfulness":0.9,"rationale":"ok"}'))
    assert maybe_auto_eval(s, run["run_id"]) is True
    assert db.run_stats(s.db_path)["auto_eval"]["faithfulness"] == 0.9
    monkeypatch.setattr(runtime, "make_llm", lambda st: (_ for _ in ()).throw(RuntimeError("judge exploded")))
    assert maybe_auto_eval(s, run["run_id"]) is True                                  # swallowed
    assert db.get_run(s.db_path, run["run_id"])["status"] == "escalated"              # run untouched
    monkeypatch.setenv("AUTO_EVAL_SAMPLE_RATE", "0.5")
    assert maybe_auto_eval(Settings(), run["run_id"], rand=lambda: 0.99) is False        # not sampled


def test_run_scenarios_resumes_from_saved_results_and_saves_intermediate_ones(env, retriever, tmp_path):
    """Provider rate limits can interrupt a long real-LLM evaluation: finished scenarios must be kept and not re-run."""
    scs = load_scenarios(default_path())
    pick = [s for s in scs if s.id.startswith(("S18-", "S08-"))]                    # two scenarios that need no research
    assert len(pick) == 2
    saved = []
    recs1, _ = ev.run_scenarios(pick[:1], "scripted", retriever, str(tmp_path), on_record=saved.append, progress=lambda *_: None)
    assert [r["id"] for r in saved] == [pick[0].id]                                   # intermediate result emitted
    lines = []
    recs2, _ = ev.run_scenarios(pick, "scripted", retriever, str(tmp_path), done={recs1[0]["id"]: recs1[0]},
                                on_record=saved.append, progress=lines.append)
    assert [r["id"] for r in recs2] == [p.id for p in pick]
    assert any("SKIP" in l and pick[0].id in l for l in lines)                        # the saved one was not re-run
    assert [r["id"] for r in saved] == [pick[0].id, pick[1].id]                       # only the new one was recorded
