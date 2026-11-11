# Evaluation report

- Generated: 2026-11-08T13:53:10+00:00  |  git: 5a322cb  |  mode: **real**  |  retriever: st
- Model: openai/gpt-oss-20b  |  research prompt: v1  |  scenarios: 1

> **REAL MODE: numbers reflect the configured model on synthetic petitions.**

> Expected outcomes encode the team's reading of the verified corpus. Scenarios flagged interpretation_dependent rest on open questions (10% = percentage points; Vice-Chancellor as decision maker; exam bye-laws not in corpus). Passing them is technical conformance, not proof of regulatory correctness.

## Deterministic metrics

| Metric | Value |
|---|---|
| Context relevance | n/a |
| Groundedness | n/a |
| Faithfulness (proxy) | n/a |
| Hallucination rate (final output) | n/a |
| Attempted hallucination rate | n/a |
| Gold-clause retrieval recall | 0.000 (n=1) |
| Route accuracy | 1.000 (n=1) |
| Escalation accuracy | 0.000 (n=1) |
| Task success rate | 0.000 (n=1) |

## LLM-judge scores (separate from the above; see docs/evaluation.md for limitations)

Not run (requires `--mode real --judge` with a configured LLM).

## By category

| Category | n | Task success | Escalation accuracy |
|---|---|---|---|
| supported | 1 | 0.0 | 0.0 |

## Scenarios

| Scenario | Result | Status | Route | Escalation | Retrieved | Interp.-dep. |
|---|---|---|---|---|---|---|
| S01-difficult-80-medical-certificate | **FAIL** | escalated | refer-to-committee | agent_error | - | yes |
