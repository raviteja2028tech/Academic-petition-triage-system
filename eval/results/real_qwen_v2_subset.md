# Evaluation report

- Generated: 2026-11-08T15:51:56+00:00  |  git: None  |  mode: **real**  |  retriever: env
- Model: qwen/qwen3.8-27b  |  research prompt: v2  |  scenarios: 3

> **REAL MODE: numbers reflect the configured model on synthetic petitions.**

> Expected outcomes encode the team's reading of the verified corpus. Scenarios flagged interpretation_dependent rest on open questions (10% = percentage points; Vice-Chancellor as decision maker; exam bye-laws not in corpus). Passing them is technical conformance, not proof of regulatory correctness.

## Deterministic metrics

| Metric | Value |
|---|---|
| Context relevance | 0.502 (n=3) |
| Groundedness | 1.000 (n=3) |
| Faithfulness (proxy) | 1.000 (n=3) |
| Hallucination rate (final output) | 0.000 (n=3) |
| Attempted hallucination rate | 0.000 (n=3) |
| Gold-clause retrieval recall | 1.000 (n=3) |
| Route accuracy | 0.667 (n=3) |
| Escalation accuracy | 0.667 (n=3) |
| Task success rate | 0.667 (n=3) |

## LLM-judge scores (separate from the above; see docs/evaluation.md for limitations)

Not run (requires `--mode real --judge` with a configured LLM).

## By category

| Category | n | Task success | Escalation accuracy |
|---|---|---|---|
| supported | 3 | 0.6667 | 0.6667 |

## Scenarios

| Scenario | Result | Status | Route | Escalation | Retrieved | Interp.-dep. |
|---|---|---|---|---|---|---|
| S01-difficult-80-medical-certificate | PASS | escalated | refer-to-committee | committee_discretion | 25ob10.0(4), 25ob10.0(5), 25ob10.0(6), 25ob10.0(7), 25ob23.0, 25ob24.1(a), 25ob32.4(a), 25ob9.0(b), 25ob9.0(c), noid-p8 | yes |
| S04-72-medical-certificate | **FAIL** | escalated | refer-to-committee | committee_discretion | 25ob10.0(1), 25ob10.0(2), 25ob10.0(3), 25ob10.0(4), 25ob10.0(5), 25ob10.0(6), 25ob10.0(7), 25ob23.0, 25ob24.1(a), 25ob32.4(a), 25ob9.0(b), 25ob9.0(c), noid-p8 | yes |
| S05-65-personal | PASS | completed | reject | - | 25ob10.0(1), 25ob10.0(2), 25ob10.0(3), 25ob10.0(4), 25ob10.0(5), 25ob10.0(6), 25ob10.0(7), 25ob15.0.1(i), 25ob23.0, 25ob24.1(a), 25ob32.4(a), 25ob32.4(b), 25ob9.0(c) | yes |
