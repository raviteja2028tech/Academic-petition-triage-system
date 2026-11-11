"""Controlled retrieval-level ablation: does a SECOND query derived from the first result's text help find the
modifying (condonation) provision?

Condition A (before): results of the first query only.
Condition B (after):  union of the first query's results and a second query derived from the top passage of the first.
The derivation is MECHANICAL and fixed in advance (below) so the experiment is deterministic and cannot leak the answer:
content words of the top passage that are not stop-words and not already in the first query, ranked by frequency then
length, top 6. This stands in for the Research Agent's LLM-chosen second query: the experiment measures whether a
second, passage-derived query is needed at all, NOT how well any LLM writes one. Gold: 25OB10.0(4) (base rule) and
25OB10.0(5) (condonation), verified in docs/corpus_verification.md.

  python -m triage.evaluation.experiment --retriever st     # real embeddings (needs EMBED_MODEL)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone

from ..config import Settings
from ..retrieval.chunk import norm_clause_id
from .run import REPO, build_retriever

GOLD = {"base": norm_clause_id("25OB10.0(4)"), "condonation": norm_clause_id("25OB10.0(5)")}
FIRST_QUERIES = [
    "minimum attendance required in each registered course",
    "what attendance is required to be eligible for the semester end examination",
    "student has 80 percent attendance in a course",
    "attendance requirement",
    "attendance shortage petition medical reasons",
    "can I write the exam if my attendance is low",
]
STOP = set("""the and for that with this from shall which their there these those will have been into than then also such
other under upon where while whose when what your they them were each every more most some only over after before
between about above below during""".split())


def derive_second_query(top_text: str, first_query: str, n: int = 6) -> str:
    seen = set(re.findall(r"[a-z]+", first_query.lower()))
    words = [w for w in re.findall(r"[a-z]{5,}", top_text.lower()) if w not in STOP and w not in seen]
    ranked = sorted(Counter(words).items(), key=lambda kv: (-kv[1], -len(kv[0]), kv[0]))
    return " ".join(w for w, _ in ranked[:n])


def run(retr, ks=(1, 3, 5)) -> dict:
    rows = []
    for strategy in ("semantic", "keyword"):
        fn = (lambda q, k: retr.semantic(q, k)) if strategy == "semantic" else (lambda q, k: retr.keyword(q, k))
        for q1 in FIRST_QUERIES:
            for k in ks:
                r1 = fn(q1, k)
                top = r1[0].text if r1 else ""
                q2 = derive_second_query(top, q1)
                r2 = fn(q2, k) if q2 else []
                a = {norm_clause_id(r.metadata["clause_id"]) for r in r1}
                b = a | {norm_clause_id(r.metadata["clause_id"]) for r in r2}
                rows.append({"strategy": strategy, "k": k, "q1": q1, "q2": q2,
                             "A_has_base": GOLD["base"] in a, "A_has_condonation": GOLD["condonation"] in a,
                             "B_has_base": GOLD["base"] in b, "B_has_condonation": GOLD["condonation"] in b})
    summary = {}
    for strategy in ("semantic", "keyword"):
        for k in ks:
            rs = [r for r in rows if r["strategy"] == strategy and r["k"] == k]
            n = len(rs)
            summary[f"{strategy}@k={k}"] = {
                "n_queries": n,
                "A_condonation_found": sum(r["A_has_condonation"] for r in rs),
                "B_condonation_found": sum(r["B_has_condonation"] for r in rs),
                "A_both_found": sum(r["A_has_base"] and r["A_has_condonation"] for r in rs),
                "B_both_found": sum(r["B_has_base"] and r["B_has_condonation"] for r in rs)}
    return {"summary": summary, "rows": rows}


def to_markdown(rep: dict) -> str:
    m = rep["meta"]
    L = ["# Experiment: effect of a derived second retrieval query", "",
         f"- Generated {m['generated_at']} | git {m['git_rev']} | retriever: **{m['retriever']}** | embedding: {m['embedding']}",
         "- Condition A: first query only. Condition B: first query + mechanically derived second query (see module docstring).",
         "- Counts are over the fixed set of 6 first-query phrasings; gold = 25OB10.0(4) base rule, 25OB10.0(5) condonation.",
         "", "> Retrieval-level ablation with a mechanical stand-in for the LLM's second query. It shows whether the second "
         "query is needed; it does NOT show how well a real LLM writes one. n=6 queries per cell: indicative only.", "",
         "| Setting | A: condonation found | B: condonation found | A: both gold found | B: both gold found |", "|---|---|---|---|---|"]
    for k, v in rep["summary"].items():
        n = v["n_queries"]
        L.append(f"| {k} | {v['A_condonation_found']}/{n} | {v['B_condonation_found']}/{n} | {v['A_both_found']}/{n} | {v['B_both_found']}/{n} |")
    L += ["", "## Derived second queries (k=3, first strategy rows)", ""]
    for r in [r for r in rep["rows"] if r["k"] == 3][:12]:
        L.append(f"- `{r['strategy']}` q1=\"{r['q1']}\" -> q2=\"{r['q2']}\" (A cond={r['A_has_condonation']}, B cond={r['B_has_condonation']})")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--retriever", choices=["hash", "st", "env"], default="st")
    ap.add_argument("--out", default=os.path.join(REPO, "eval", "results", "experiment_second_query.json"))
    a = ap.parse_args(argv)
    s = Settings()
    if a.retriever == "st" and not s.embed_model:
        print("ERROR: --retriever st needs EMBED_MODEL in the environment (see .env.example). Nothing was run.", file=sys.stderr)
        return 2
    retr = build_retriever(a.retriever, s)
    rep = run(retr)
    import subprocess
    try:
        rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:  # noqa: BLE001
        rev = ""
    rep["meta"] = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "git_rev": rev or None,
                   "retriever": a.retriever, "embedding": retr.embedder.tag}
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump(rep, open(a.out, "w", encoding="utf8"), indent=1)
    md = os.path.splitext(a.out)[0] + ".md"
    open(md, "w", encoding="utf8", newline="\n").write(to_markdown(rep))
    print(to_markdown(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
