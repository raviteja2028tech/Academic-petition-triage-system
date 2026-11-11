> **Update (2026-11-08).** Real-LLM evaluation has now been run on two models and prompt v2 on a subset: see `docs/EVALUATION_REPORT.md` (generated from `eval/results/`). The definitions and limitations below still apply.

# Evaluation methodology and results

Reproduce: `python -m triage.evaluation.run --mode scripted --retriever hash` (offline) or `--mode real` (needs an LLM).
Reports: `eval/results/*.json` (machine readable) and `*.md` (readable). Scenarios: `eval/scenarios.json`.

## Two modes — read this before quoting any number
| Mode | Model | What the numbers mean |
|------|-------|-----------------------|
| `scripted` | A deterministic script per scenario (`evaluation/scripted.py`) | Verifies the **pipeline's safety machinery** (citation verification, guardrails, escalation, degradation) under a *specified* model behaviour. 100 % here is a statement about the harness, **not** about any LLM. Recall/relevance reflect the scripted queries. |
| `real` | The configured LLM (`LLM_BASE_URL`, …) | The only mode that says anything about a model. **Not run yet** (no provider configured on the development machine). |

## Scenario set (28, all synthetic petitions)
Categories: supported attendance (incl. the assignment's difficult case, 78/80/82 % medical, 72 %/65 % below the band), missing
documentation, unsupported types (4), conflicting evidence (text vs fields, declared-vs-actual type, model-reported conflict),
missing evidence, fabricated citations (invented quote; invented clause), prompt injection (3) + abusive text, output safety
(final-decision wording; direct grant resting on an authority-reserved clause), provider failure (outage, breaker open, invalid
output), ambiguous petition, and a benign petition containing the words "instructions"/"previous" (false-positive check).
Each scenario has: input petition, scripted behaviour, expected status / route / escalation required / escalation reason,
whether an LLM call is expected, and **gold clauses**.

**Gold clauses are restricted by code** (`VERIFIED_GOLD`) to clauses actually read in the supplied PDF: `25OB10.0(4)`, `25OB10.0(5)`,
`25OB10.0(7)`, `25OB23.0` (docs/corpus_verification.md V2–V5). Loading a scenario with any other gold clause raises an error
(tested). The regulations are never mocked; the corpus is the real VTU PDF. Expected outcomes encode the team's reading of that
corpus; 13 of 28 scenarios are flagged `interpretation_dependent` because they rest on unresolved questions (10 % = percentage points;
Vice-Chancellor as the decision maker; exam bye-laws absent). **Passing them is technical conformance, not proof of regulatory
correctness.**

## Metrics (deterministic; `evaluation/metrics.py`)
| Metric | Definition | Applies to |
|---|---|---|
| Context relevance | retrieved passages in a gold clause or its clause family (same root, e.g. `25OB10.0(*)`) ÷ retrieved passages | scenarios with gold and ≥1 retrieved passage |
| Gold-clause recall | gold clauses retrieved at least once ÷ gold clauses | scenarios with gold |
| Groundedness | final citations whose quote is a verbatim (whitespace-normalised) substring of the chunk **re-read from the index by the evaluator** ÷ final citations | runs with ≥1 citation |
| Faithfulness (proxy) | 1 if every citation is grounded **and** every percentage in position/basis is traceable to cited text, the petition's figure, or a difference/sum of those; else 0 | runs with a determination |
| Hallucination rate | runs with a determination that contain an ungrounded citation or untraceable figure ÷ runs with a determination | same (expected 0 by construction: tripwire) |
| Attempted-hallucination rate | LLM-using runs where the verifier rejected ≥1 model citation or the numeric guardrail fired ÷ LLM-using runs | LLM-using runs (this is where a model's hallucination shows up) |
| Route accuracy | route == expected route | scenarios asserting a route |
| Escalation accuracy | `escalation.required` (and reason, when asserted) == expected | all |
| Task success | status, route, escalation, "LLM called or not" all as expected **and** all citations grounded **and** recall = 1 where gold exists | all |

Every metric is reported with `n`; a metric with `n = 0` is `null`, never 0. Faithfulness is a **proxy**: it cannot judge legal logic
(e.g. whether 80 % really is inside a condonable band) — that stays a human judgement, as does whether a *cited, grounded* passage
actually entails the conclusion.

## LLM-judge scores (separate; `evaluation/judge.py`, `prompts/judge_v1.yaml`)
Optional (`--mode real --judge`), reported in their own section and **never merged** into the deterministic metrics. Limitations: non-deterministic;
may be lenient or favour fluent text; a judge from the same model family as the system tends to over-rate it; it sees only the passages shown
so it cannot catch a wrong-but-grounded conclusion; 28 scenarios are anecdotal, not statistically meaningful. A judge failure is recorded and
ignored. **Not run** (no real LLM). The judge is unit-tested with a scripted judge only.
Sampled auto-evaluation of live runs exists (`AUTO_EVAL_SAMPLE_RATE`, default 0): it runs after the run is finalised inside a catch-all so it can
never alter or fail a petition run (tested).

## Results actually obtained
### Scripted mode, hash embedder, 28 scenarios (`eval/results/scripted_hash.{json,md}`)
Task success 28/28; route accuracy 28/28; escalation accuracy 28/28; groundedness 1.0 (n=10); faithfulness 1.0 (n=10); hallucination rate 0.0
(n=10); attempted-hallucination 2/24 (the two fabricated-citation scenarios, both caught); gold recall 1.0 (n=13); **context relevance 0.415 (n=13)**. (Regenerated 2026-10-29 after the ambiguity fix changed scenario S27; earlier figures were n=11/14 and 0.414.)
Interpretation: the safety machinery behaves as specified. The 0.414 relevance is a real signal even here: with `k=5` keyword search returns many
passages from other attendance-related clauses; precision is the weak spot, recall is fine.
A finding the evaluation itself produced: the first run scored 24/28 because I expected unsupported petition types to need **no** LLM call; the
implemented behaviour is one triage call, then escalation before any retrieval. I corrected the expectation (and the scripted behaviour) to match
the implementation rather than changing the working pipeline.

### Experiment 1 — does a derived second retrieval query help? (`eval/results/experiment_second_query.{json,md}`)
Retrieval-level ablation with real sentence-transformer embeddings (`all-MiniLM-L6-v2`), 6 fixed first-query phrasings, mechanical second query derived
from the top passage (fixed in advance; not tuned afterwards). Condition A = first query only; B = first + second.

| Setting | A: condonation found | B: condonation found | A: both gold | B: both gold |
|---|---|---|---|---|
| semantic k=1 | 3/6 | 3/6 | 0/6 | 0/6 |
| semantic k=3 | 5/6 | 5/6 | 2/6 | 2/6 |
| semantic k=5 | 5/6 | 5/6 | 4/6 | 4/6 |
| keyword k=1/3/5 | 1/6, 2/6, 2/6 | 1/6, 2/6, 2/6 | 0/6 | 0/6 |

**Result: no measurable effect.** The mechanical second queries (e.g. "participation coordinator chairperson activities principal programme") were not
better than the first query. Honest reading: (1) the claim that "a second, passage-derived query is needed" is **not supported** for this corpus by this
experiment — semantic search already surfaces 25OB10.0(5) in the top 5 for 5/6 phrasings; (2) the derivation is a crude stand-in for an LLM-written query,
so this does **not** show an LLM-written second query would not help; (3) n = 6 per cell is indicative only. Separately it shows keyword (BM25) search is weak
at finding the condonation clause (2/6), and that finding *both* gold clauses in one top-5 happens only 4/6 times for semantic search — which is why the
Research agent has `get_clause`/`get_neighbouring_clauses` tools and the verifier requires the cited evidence to have been retrieved.

### Experiment 2 — prompt variants (`prompts/research_v1.yaml` vs `research_v2.yaml`)
v2 is a more prescriptive strategy (neighbour clauses + a generic "modifying provisions" search before finishing). **Not run**: a scripted model ignores prompt
text, so a comparison would be vacuous (the `compare` command says so). Run with a real LLM:
`python -m triage.evaluation.run --mode real --research-prompt v1 --out eval/results/real_v1.json` then `... v2 ... real_v2.json`, then
`python -m triage.evaluation.run compare eval/results/real_v1.json eval/results/real_v2.json`. No improvement is claimed.

## Known weaknesses of this evaluation
* Scripted mode cannot reveal prompt or model problems; the real-LLM evaluation is the main outstanding gap.
* 28 scenarios, one author, expectations written by the same team that wrote the system.
* Hash embedder in the default offline run (semantic search weak); the experiment above used the real model.
* Gold labels cover only the four verified clauses; other relevant provisions (e.g. 25OB8.2(iv), 25OB9.0) are not gold, so relevance is understated.
