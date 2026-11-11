"""Evaluation CLI.

  python -m triage.evaluation.run --mode scripted --retriever hash
  python -m triage.evaluation.run --mode real --retriever st            # needs LLM_* env + EMBED_MODEL
  python -m triage.evaluation.run --mode real --research-prompt v2 --out eval/results/real_v2.json
  python -m triage.evaluation.run compare eval/results/a.json eval/results/b.json

Modes
  scripted  a deterministic scripted model per scenario. Measures the pipeline's verification / guardrail / escalation
            machinery. It does NOT measure LLM quality, and recall/relevance here reflect the scripted queries.
  real      the configured LLM (LLM_BASE_URL, LLM_MODEL, ...). The only mode whose numbers say anything about a model.
Outputs: a machine-readable JSON file and a Markdown report next to it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from .. import db
from ..agents import runtime
from ..config import Settings
from ..llm.client import LLMNotConfigured
from ..llm.prompts import load_prompt
from . import metrics as M
from . import scripted
from .judge import judge_run
from .scenarios import Scenario, default_path, load_scenarios

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))


def build_retriever(kind: str, s: Settings):
    """hash: real PDF, test-only hashing embedder (keyword/clause strong, semantic weak). st: real sentence-transformer
    (needs EMBED_MODEL). env: the configured Chroma server."""
    if kind == "env":
        return runtime.make_retriever(s)
    import chromadb
    from ..retrieval.embed import HashEmbedder, SentenceTransformerEmbedder
    from ..retrieval.ingest import run_ingest
    from ..retrieval.search import Retriever
    from ..retrieval.store import ChromaStore
    os.environ["CHROMA_COLLECTION"] = "eval" + uuid.uuid4().hex[:8]
    s2 = Settings()
    emb = HashEmbedder() if kind == "hash" else SentenceTransformerEmbedder(s2.embed_model, s2.hf_home or None)
    client = chromadb.EphemeralClient()
    pdfs = [os.path.join(s2.corpus_dir, f) for f in sorted(os.listdir(s2.corpus_dir)) if f.lower().endswith(".pdf")]
    m = run_ingest(s2, emb, client, pdfs, record=False)
    if m["status"] != "success":
        raise SystemExit(f"cannot build evaluation index: {m['errors']}")
    return Retriever(ChromaStore(client, s2.chroma_collection, emb.tag), emb)


def _git_rev() -> Optional[str]:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True,
                              timeout=5).stdout.strip() or None
    except Exception:  # noqa: BLE001
        return None


def run_scenarios(scs: list[Scenario], mode: str, retriever, tmp: str, research_prompt: str = "v1",
                  judge: bool = False, progress=print, done: Optional[dict] = None, pause: float = 0.0,
                  on_record=None) -> tuple[list[dict], dict]:
    """done: already-finished records by scenario id (resume). pause: seconds to sleep after each real-LLM scenario so a
    tokens-per-minute provider limit can refill. on_record(rec): called after every scenario (intermediate results)."""
    recs, judged = [], []
    done = done or {}
    os.environ["DB_PATH"] = os.path.join(tmp, "eval.sqlite3")
    os.environ["AGENT_MODE"] = "agents"
    os.environ.setdefault("PROMPTS_DIR", os.path.join(REPO, "prompts"))
    os.environ["RESEARCH_PROMPT_VERSION"] = research_prompt
    for sc in scs:
        if sc.id in done:
            recs.append(done[sc.id])
            if done[sc.id].get("judge"):
                judged.append(done[sc.id]["judge"])
            progress(f"  SKIP  {sc.id}  (resumed from saved result)")
            continue
        saved = {k: os.environ.get(k) for k in sc.settings_override}
        os.environ.update(sc.settings_override)
        try:
            s = Settings()
            if mode == "scripted":
                llm = scripted.build(sc.llm_behaviour, sc.petition)
            else:
                llm = runtime.make_llm(s)
            run_id = db.create_run(s.db_path, sc.petition, "eval", "eval-" + sc.id)
            t0 = time.time()
            runtime.run_pipeline(s, run_id, llm=llm, retriever=retriever)
            run = db.get_run(s.db_path, run_id)
            rec = M.score_run(sc, run, retriever)
            rec["latency_s"] = round(time.time() - t0, 3)
            if judge and mode == "real":
                prompt = load_prompt(s.prompts_dir, "judge", "v1")
                passages = []
                for e in (run["result"] or {}).get("evidence_reviewed", []):
                    ch = retriever.get_chunk(e["chunk_id"])
                    if ch:
                        passages.append({"evidence_id": e["evidence_id"], "clause_id": e["clause_id"], "text": ch.text})
                rec["judge"] = judge_run(llm, prompt, sc.petition, run["result"] or {}, passages)
                judged.append(rec["judge"])
            recs.append(rec)
            if on_record:
                on_record(rec)
            progress(f"  {'PASS' if rec['task_success'] else 'FAIL'}  {sc.id}  ->  {rec['status']}/{rec['route']}/{rec['escalation_reason']}")
            if mode == "real" and pause and sc is not scs[-1] and sc.expected.llm_called:
                time.sleep(pause)
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    judge_summary: dict = {"enabled": bool(judge and mode == "real")}
    if judge_summary["enabled"]:
        ok = [j for j in judged if j.get("status") == "ok"]
        judge_summary.update(runs_scored=len(ok), runs_failed=len(judged) - len(ok))
        for k in ("context_relevance", "groundedness", "faithfulness"):
            v = [j[k] for j in ok if k in j]
            judge_summary[k] = {"value": M.mean(v), "n": len(v)}
    return recs, judge_summary


def build_report(scs, recs, mode, retriever_kind, research_prompt, judge_summary, tmp) -> dict:
    s = Settings()
    corpus = [f for f in os.listdir(s.corpus_dir) if f.lower().endswith(".pdf")] if os.path.isdir(s.corpus_dir) else []
    sha = {f: hashlib.sha256(open(os.path.join(s.corpus_dir, f), "rb").read()).hexdigest() for f in corpus}
    return {
        "meta": {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "mode": mode,
                 "retriever": retriever_kind, "git_rev": _git_rev(), "scenario_count": len(scs),
                 "research_prompt_version": research_prompt, "corpus_sha256": sha,
                 "model": ("scripted (no real model)" if mode == "scripted" else (s.llm_model or "unconfigured")),
                 "interpretation": ("SCRIPTED MODE: these numbers verify the pipeline's safety machinery (verification, "
                                    "guardrails, escalation, degradation) under specified model behaviours. They are NOT a "
                                    "measure of any LLM's quality, and recall/relevance reflect the scripted queries."
                                    if mode == "scripted" else
                                    "REAL MODE: numbers reflect the configured model on synthetic petitions."),
                 "regulatory_caveat": ("Expected outcomes encode the team's reading of the verified corpus. Scenarios flagged "
                                       "interpretation_dependent rest on open questions (10% = percentage points; "
                                       "Vice-Chancellor as decision maker; exam bye-laws not in corpus). Passing them is "
                                       "technical conformance, not proof of regulatory correctness.")},
        "metrics": M.aggregate(recs), "llm_judge": judge_summary, "by_category": M.by_category(recs),
        "scenarios": recs,
    }


def _fmt(m: dict) -> str:
    return "n/a" if m["value"] is None else f"{m['value']:.3f} (n={m['n']})"


def to_markdown(rep: dict) -> str:
    m, meta = rep["metrics"], rep["meta"]
    L = ["# Evaluation report", "",
         f"- Generated: {meta['generated_at']}  |  git: {meta['git_rev']}  |  mode: **{meta['mode']}**  |  retriever: {meta['retriever']}",
         f"- Model: {meta['model']}  |  research prompt: {meta['research_prompt_version']}  |  scenarios: {meta['scenario_count']}", "",
         f"> **{meta['interpretation']}**", "", f"> {meta['regulatory_caveat']}", "",
         "## Deterministic metrics", "", "| Metric | Value |", "|---|---|"]
    names = [("Context relevance", "context_relevance"), ("Groundedness", "groundedness"), ("Faithfulness (proxy)", "faithfulness"),
             ("Hallucination rate (final output)", "hallucination_rate"), ("Attempted hallucination rate", "attempted_hallucination_rate"),
             ("Gold-clause retrieval recall", "gold_clause_recall"), ("Route accuracy", "route_accuracy"),
             ("Escalation accuracy", "escalation_accuracy"), ("Task success rate", "task_success_rate")]
    L += [f"| {n} | {_fmt(m[k])} |" for n, k in names]
    j = rep["llm_judge"]
    L += ["", "## LLM-judge scores (separate from the above; see docs/evaluation.md for limitations)", ""]
    if j.get("enabled"):
        L += ["| Metric | Value |", "|---|---|"] + [f"| {k} | {_fmt(j[k])} |" for k in ("context_relevance", "groundedness", "faithfulness")]
        L += ["", f"Runs scored: {j['runs_scored']}, judge failures: {j['runs_failed']}."]
    else:
        L += ["Not run (requires `--mode real --judge` with a configured LLM)."]
    L += ["", "## By category", "", "| Category | n | Task success | Escalation accuracy |", "|---|---|---|---|"]
    L += [f"| {c} | {v['n']} | {v['task_success']} | {v['escalation_accuracy']} |" for c, v in rep["by_category"].items()]
    L += ["", "## Scenarios", "", "| Scenario | Result | Status | Route | Escalation | Retrieved | Interp.-dep. |", "|---|---|---|---|---|---|---|"]
    for r in rep["scenarios"]:
        L.append(f"| {r['id']} | {'PASS' if r['task_success'] else '**FAIL**'} | {r['status']} | {r['route']} | "
                 f"{r['escalation_reason'] or '-'} | {', '.join(r['retrieved_clauses']) or '-'} | {'yes' if r['interpretation_dependent'] else ''} |")
    return "\n".join(L) + "\n"


def compare(a_path: str, b_path: str) -> str:
    a, b = (json.load(open(p, encoding="utf8")) for p in (a_path, b_path))
    L = [f"# Comparison: A = {os.path.basename(a_path)} (research prompt {a['meta']['research_prompt_version']}, {a['meta']['mode']}) "
         f"vs B = {os.path.basename(b_path)} (research prompt {b['meta']['research_prompt_version']}, {b['meta']['mode']})", "",
         "| Metric | A | B | B - A |", "|---|---|---|---|"]
    for k, v in a["metrics"].items():
        va, vb = v["value"], b["metrics"][k]["value"]
        d = "n/a" if va is None or vb is None else f"{vb - va:+.3f}"
        L.append(f"| {k} | {'n/a' if va is None else f'{va:.3f}'} | {'n/a' if vb is None else f'{vb:.3f}'} | {d} |")
    diff = [(x["id"], x["task_success"], y["task_success"]) for x, y in zip(a["scenarios"], b["scenarios"]) if x["task_success"] != y["task_success"]]
    L += ["", f"Scenarios whose pass/fail changed: {len(diff)}"] + [f"- {i}: {x} -> {y}" for i, x, y in diff]
    if a["meta"]["mode"] == "scripted" or b["meta"]["mode"] == "scripted":
        L += ["", "> One or both runs used a SCRIPTED model, which ignores prompt text: prompt variants cannot differ in scripted mode."]
    n = min(a["meta"]["scenario_count"], b["meta"]["scenario_count"])
    L += ["", f"> Sample size is {n} scenarios; differences of a few scenarios are not statistically meaningful."]
    return "\n".join(L) + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "compare":
        print(compare(argv[1], argv[2]))
        return 0
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["scripted", "real"], default="scripted")
    ap.add_argument("--retriever", choices=["hash", "st", "env"], default="hash")
    ap.add_argument("--scenarios", default=default_path())
    ap.add_argument("--research-prompt", default="v1")
    ap.add_argument("--judge", action="store_true", help="also score with the LLM judge (real mode only)")
    ap.add_argument("--only", help="comma-separated scenario id prefixes")
    ap.add_argument("--pause", type=float, default=0.0, help="seconds to wait after each real-LLM scenario (rate-limit refill)")
    ap.add_argument("--resume", action="store_true", help="skip scenarios already saved in <out>.partial.json and keep going")
    ap.add_argument("--rerun", default="", help="with --resume: comma-separated scenario id prefixes to run again even if saved")
    ap.add_argument("--out", default=os.path.join(REPO, "eval", "results", "latest.json"))
    a = ap.parse_args(argv)
    scs = load_scenarios(a.scenarios)
    if a.only:
        pre = tuple(a.only.split(","))
        scs = [s for s in scs if s.id.startswith(pre)]
    s = Settings()
    if a.mode == "real" and (not s.llm_base_url or not s.llm_model):
        print("ERROR: --mode real needs LLM_BASE_URL and LLM_MODEL (and LLM_API_KEY if required) in the environment. "
              "Nothing was run; no results were fabricated.", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        print(f"building '{a.retriever}' retriever from the corpus ...")
        retr = build_retriever(a.retriever, s)
        print(f"running {len(scs)} scenarios ({a.mode}) ...")
        partial = a.out + ".partial.json"
        done: dict = {}
        if a.resume and os.path.isfile(partial):
            rerun = tuple(x for x in a.rerun.split(",") if x)
            done = {r["id"]: r for r in json.load(open(partial, encoding="utf8")) if not (rerun and r["id"].startswith(rerun))}
            print(f"resuming: {len(done)} saved scenario result(s) kept")
        saved_recs = dict(done)

        def on_record(rec: dict) -> None:       # intermediate results survive a crash or an interrupted run
            saved_recs[rec["id"]] = rec
            json.dump(list(saved_recs.values()), open(partial, "w", encoding="utf8"), ensure_ascii=False)

        recs, judge_summary = run_scenarios(scs, a.mode, retr, tmp, a.research_prompt, a.judge, done=done, pause=a.pause,
                                            on_record=on_record)
        rep = build_report(scs, recs, a.mode, a.retriever, a.research_prompt, judge_summary, tmp)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump(rep, open(a.out, "w", encoding="utf8"), indent=1, ensure_ascii=False)
    md = os.path.splitext(a.out)[0] + ".md"
    open(md, "w", encoding="utf8", newline="\n").write(to_markdown(rep))
    t = rep["metrics"]["task_success_rate"]
    print(f"\ntask success {t['value']:.3f} over {t['n']} scenarios -> {a.out} and {md}")
    return 0 if t["value"] == 1.0 else 1


if __name__ == "__main__":
    sys.exit(main())
