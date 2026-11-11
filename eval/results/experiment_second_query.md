# Experiment: effect of a derived second retrieval query

- Generated 2026-10-28T12:51:14+00:00 | git 5a322cb | retriever: **st** | embedding: st|all-MiniLM-L6-v2|dim384|norm|clause-v1
- Condition A: first query only. Condition B: first query + mechanically derived second query (see module docstring).
- Counts are over the fixed set of 6 first-query phrasings; gold = 25OB10.0(4) base rule, 25OB10.0(5) condonation.

> Retrieval-level ablation with a mechanical stand-in for the LLM's second query. It shows whether the second query is needed; it does NOT show how well a real LLM writes one. n=6 queries per cell: indicative only.

| Setting | A: condonation found | B: condonation found | A: both gold found | B: both gold found |
|---|---|---|---|---|
| semantic@k=1 | 3/6 | 3/6 | 0/6 | 0/6 |
| semantic@k=3 | 5/6 | 5/6 | 2/6 | 2/6 |
| semantic@k=5 | 5/6 | 5/6 | 4/6 | 4/6 |
| keyword@k=1 | 1/6 | 1/6 | 0/6 | 0/6 |
| keyword@k=3 | 2/6 | 2/6 | 0/6 | 0/6 |
| keyword@k=5 | 2/6 | 2/6 | 0/6 | 0/6 |

## Derived second queries (k=3, first strategy rows)

- `semantic` q1="minimum attendance required in each registered course" -> q2="participation coordinator chairperson activities principal programme" (A cond=True, B cond=True)
- `semantic` q1="what attendance is required to be eligible for the semester end examination" -> q2="courses examinations prescribed semesters requirement university" (A cond=False, B cond=False)
- `semantic` q1="student has 80 percent attendance in a course" -> q2="registered required minimum cannot fulfil secure" (A cond=True, B cond=True)
- `semantic` q1="attendance requirement" -> q2="shortage students college teacher candidates counselled" (A cond=True, B cond=True)
- `semantic` q1="attendance shortage petition medical reasons" -> q2="participation coordinator course chairperson activities principal" (A cond=True, B cond=True)
- `semantic` q1="can I write the exam if my attendance is low" -> q2="participation coordinator course chairperson activities principal" (A cond=True, B cond=True)
- `keyword` q1="minimum attendance required in each registered course" -> q2="student cannot fulfil secure" (A cond=False, B cond=False)
- `keyword` q1="what attendance is required to be eligible for the semester end examination" -> q2="education learning outcome based particularly professional" (A cond=False, B cond=False)
- `keyword` q1="student has 80 percent attendance in a course" -> q2="registered required minimum cannot fulfil secure" (A cond=False, B cond=False)
- `keyword` q1="attendance requirement" -> q2="course satisfying permitted semester students grades" (A cond=False, B cond=False)
- `keyword` q1="attendance shortage petition medical reasons" -> q2="participation coordinator course chairperson activities principal" (A cond=True, B cond=True)
- `keyword` q1="can I write the exam if my attendance is low" -> q2="committee evaluation moderation university concerned conducted" (A cond=True, B cond=True)
