# Academic Regulation and Student Petition Triage

Mini Project 15 — ML System Design & AgentOps (UE24AM342AA5), PESU.

Students submit **synthetic** academic petitions. Three AI agents (Triage → Research → Verifier) retrieve the relevant university regulations,
verify every citation against the source text and produce a **recommendation**. Uncertain cases are escalated. A **human examiner**
records the final decision, stored separately from the AI output. **The AI never makes the final decision.**

> **Honest status** (details and evidence: [`PROJECT_STATUS.md`](PROJECT_STATUS.md), [`TESTING_REPORT.md`](TESTING_REPORT.md), [`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md))
> * A **real LLM completes the three-agent flow end to end** (Groq-hosted `openai/gpt-oss-120b` and `qwen/qwen3.8-27b`). The difficult case (80 % attendance + medical
>   certificate) was run with real models and escalated to a human with two verified citations (25OB10.0(4) p18, 25OB10.0(5) p19).
> * It is **not** claimed that the regulatory interpretation is right: the examination bye-laws are not in the corpus, "10 %" and the deciding authority are unconfirmed.
> * **Genuine Role-Based Authentication.** Separate student and examiner login portals (`/student/login` and `/examiner/login`), bcrypt password hashing, session tokens, student privacy isolation, and attributed human decisions.
> * Only attendance petitions are analysed; other categories always escalate.

## Demonstration Accounts & Synthetic Dataset

The system includes pre-seeded, idempotent synthetic demonstration accounts covering distinct academic cases:

### Synthetic Students (Password: `Student@123`)

| Student ID | USN | Full Name | Department / Branch | Sem / Sec | Seeded Petition Case | Status |
|---|---|---|---|---|---|---|
| `STU2026001` | `SYN-202601` | Alex Mercer | Computer Science & Engineering | Sem 6 (A) | Case 1: 80.0% attendance, hospitalisation (CS101)<br>Case 2: 71.0% attendance, below floor (MATH201) | **Accepted** (Dr. Vance)<br>**Rejected** (Dr. Vance) |
| `STU2026002` | `SYN-202602` | Priya Sharma | Information Science & Engineering | Sem 4 (B) | Case 3: 77.8% attendance, University Sports duty leave (IS204) | **Awaiting Board Ruling** *(Ready for live examiner evaluation!)* |
| `STU2026003` | `SYN-202603` | Marcus Chen | Electronics & Communication Engineering | Sem 2 (C) | Case 4: 81.25% attendance, bereavement without proof (EC102) | **Info Requested** (Prof. Kulkarni) |

### Examination Board Officers (Password: `Examiner@123`)

| Examiner ID | Full Name | Official Role | Access Scope |
|---|---|---|---|
| `EXM2026001` | Dr. Eleanor Vance | Examination Board Chairperson | Priority queue, AI citations, record binding accept/reject determinations |
| `EXM2026002` | Prof. Rajesh Kulkarni | Member Secretary | Review evidence, request additional student documentation |

*Portal Access URLs:*
- **Portal Selection Gateway:** [`http://localhost:8080/`](http://localhost:8080/)
- **Student Portal Login:** [`http://localhost:8080/student/login`](http://localhost:8080/student/login)
- **Student Profile Dossier:** [`http://localhost:8080/student/profile`](http://localhost:8080/student/profile)
- **Examiner Board Login:** [`http://localhost:8080/examiner/login`](http://localhost:8080/examiner/login)
- **Examiner Review Queue:** [`http://localhost:8080/examiner/queue`](http://localhost:8080/examiner/queue)

## Quick start (Docker)

```bash
cp .env.example .env
# edit .env: LLM_BASE_URL, LLM_API_KEY, LLM_MODEL (any OpenAI-compatible chat API). Never commit .env. Leave blank to run without a model:
# every petition then escalates with reason "llm_unavailable" and no fake answer.
docker compose up -d --build      # first build downloads CPU torch and, on first ingest, the embedding model: be patient
docker compose ps                 # api, worker, redis, chroma, web, ui healthy; `ingest` exits 0 after indexing 197 chunks
```

| URL (bound to 127.0.0.1) | What |
|---|---|
| http://localhost:8080 | **React app** – Student, Examiner and System portals (primary UI) |
| http://localhost:8000/docs | FastAPI OpenAPI docs · `/readyz` · `/metrics` |
| http://localhost:8501 | Streamlit UI (earlier UI, kept as a fallback) |

```bash
docker compose up -d --scale worker=3             # more workers
docker compose run --rm ingest                    # re-index (idempotent)
docker compose --profile observability up -d      # Jaeger :16686, Prometheus :9090, Grafana :3000, cAdvisor :8081
                                                  #   (also set OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4318 in .env, then recreate api and worker)
docker compose down                               # stop, keep data;  `down -v` also deletes the database, index and caches
```

**Rate-limited LLM keys.** One full analysis uses ~13k–23k tokens. With an 8000-tokens/minute key it takes 2–3 minutes; with a daily quota (e.g. 200,000/day)
about 10 petitions fit per day. The client paces itself from the provider's headers and fails fast (escalating, not waiting) when a quota is exhausted.

### Run without an API key (stub model, for demos and load tests)
```bash
docker compose --profile loadtest up -d --build llm-stub
LLM_BASE_URL=http://llm-stub:9100/v1 LLM_MODEL=stub-model LLM_API_KEY= docker compose --profile loadtest up -d --force-recreate worker api
```
The UI then shows "Produced by a stub / scripted model". Retrieval and citation verification are real; the recommendation text is scripted.

### Frontend development
```bash
cd frontend && npm ci
npm run dev        # http://localhost:5173, proxies /api to http://localhost:8000
npm run build      # type-check + production build
npm test           # Vitest + Testing Library
```

## What is in the repository

| Path | Contents |
|---|---|
| `src/triage/` | `api/` FastAPI · `worker/` RQ tasks · `agents/` LangGraph graph, three agents, tools, policy · `llm/` OpenAI-compatible client · `reliability/` retry, breaker, cache, rate limit · `retrieval/` ingest, chunking, embeddings, Chroma, BM25, hybrid · `guardrails/` · `evaluation/` · `observability/` |
| `frontend/` | React + Vite + TypeScript + Tailwind + shadcn/ui-style components; nginx Dockerfile |
| `ui/` | Streamlit fallback UI |
| `prompts/` | Versioned agent prompts (`triage_v1`, `research_v1/v2`, `verifier_v1`, `judge_v1`) |
| `corpus/` | Source PDF, `SOURCES.md`, `verified_passages.json` |
| `eval/` | `scenarios.json` (28 synthetic scenarios) and `results/` |
| `loadtest/` | Locust file, LLM stub, benchmark orchestrator, failure drills, results |
| `e2e/` | Browser end-to-end script |
| `tests/` · `scripts/` | pytest suite · secret scan, security probe, evaluation report generator |
| `docs/` | Detailed notes per topic and the generated `EVALUATION_REPORT.md` |

Top-level documents: [`ARCHITECTURE.md`](ARCHITECTURE.md) · [`PROJECT_STATUS.md`](PROJECT_STATUS.md) · [`TESTING_REPORT.md`](TESTING_REPORT.md) ·
[`SYSTEM_TESTING_REPORT.md`](SYSTEM_TESTING_REPORT.md) · [`LOAD_TEST_REPORT.md`](LOAD_TEST_REPORT.md) · [`SECURITY_REVIEW.md`](SECURITY_REVIEW.md) ·
[`DEMO_GUIDE.md`](DEMO_GUIDE.md) · [`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md) · [`docs/EVALUATION_REPORT.md`](docs/EVALUATION_REPORT.md) · [`SPEC.md`](SPEC.md)

## Configuration
Everything comes from environment variables (`.env.example` documents each one). Highlights: `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`; optional `FALLBACK_LLM_*`;
`MAX_RUN_SECONDS` (default in `.env.example` 450; the RQ job timeout follows it); `LLM_RATE_LIMIT_MAX_ATTEMPTS`; `RATE_LIMIT_REQUESTS`; `CACHE_ENABLED`;
`CORS_ORIGINS` (off by default; the bundled web app is same-origin through nginx); `PRICE_*` (cost shows as "unknown" without prices).
`EMBED_MODEL` names the local embedding model so the first `docker compose up` works (open question SPEC A-3: confirm with course staff whether that is allowed).

## Tests and checks
```bash
pip install -r requirements-dev.txt
python -m pytest -q                         # Python suite (real-model tests skip when unconfigured; see TESTING_REPORT.md)
cd frontend && npm test && npm run build    # frontend unit tests + type-check + build
python scripts/check_no_secrets.py          # credential scan of tracked/unignored files
python scripts/security_probe.py            # black-box probe of the running stack
python loadtest/benchmark.py --suite quick  # then --suite all; needs Docker, uses the stub LLM
python loadtest/failure_drills.py           # real container stop/start drills (run against the stub stack)
PYTHONPATH=src python -m triage.evaluation.run --mode scripted --retriever hash     # safety machinery, NOT an LLM
# real model (inside Docker so Redis/Chroma are reachable):
docker compose run --rm worker python -m triage.evaluation.run --mode real --retriever env --pause 60 --resume --out /app/eval/results/real.json
python scripts/make_eval_report.py          # rebuild docs/EVALUATION_REPORT.md from eval/results
```

## Safety design in one paragraph
Petition text and retrieved passages are untrusted. Triage escalates injection/abuse text without calling the model. The model can only call allow-listed, validated retrieval
tools. The verifier accepts a citation only if its quote is a verbatim substring of the re-read indexed chunk; page, clause and document come from the index. Policy code blocks
final-decision wording, ungrounded numbers, grants resting on clauses that reserve the decision to an authority, and AI *rejections* inside the band that the regulation reserves to the
Vice-Chancellor. Every failure (provider, retrieval, malformed output, budget, breaker) ends in an escalation with no determination.
