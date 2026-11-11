# Known limitations

Each item says whether it is a **code limitation** (could be improved here), a **provider limitation**, or an **external blocker**
(needs information or approval from outside this repository). Nothing in the second and third groups has been faked or assumed.

## A. External blockers (need the university or another outside party)

These were deliberately **not** worked around. The system keeps the uncertainty visible (see `open_questions` in every attendance result).

| # | What is needed | Why it matters | Where it shows up |
|---|---|---|---|
| E1 | The **examination bye-laws** (the assignment names them) | Not in the supplied corpus; any rule that lives only there is invisible to the system. | `corpus/SOURCES.md`, `docs/corpus_verification.md` §4, open question OQ4 |
| E2 | **Meaning of "10 %"** in clause 25OB10.0(5): 10 percentage points (floor 75 %) or 10 % of 85 % (floor 76.5 %) | Decides who is inside the condonable band. Table 25OB23.0.1 (DX below 75 %) supports percentage points, but it is an inference. | OQ1; policy constants `ATTENDANCE_BASE_PCT`, `CONDONABLE_FLOOR_PP_PCT` |
| E3 | **Who decides** condonation: the clause says the Vice-Chancellor on the recommendation of the Dean/Principal/Chairperson/Programme Coordinator, while the assignment says "committee" | The route `refer-to-committee` is an interpretation. | OQ2 |
| E4 | What a **valid medical certificate** must contain, and whether a certificate alone qualifies | Not stated in the clause ("valid documentary evidence"). The AI never judges a certificate. | OQ3 |
| E5 | **Official source URL, retrieval date and redistribution licence** of the regulations PDF | The supplied copy was produced by an online PDF tool and is not provably a byte-identical official download. Do not publish the repository publicly until this is confirmed. | `corpus/SOURCES.md` |
| E6 | Whether **autonomous colleges' own rules** differ from these regulations | Clause 1.2 says these regulations apply to them; not independently verified. | `docs/corpus_verification.md` |
| E7 | Confirmation of a **22-vs-30 requirement** question raised in earlier notes | Unresolved in the corpus. | `PROJECT_STATUS.md` |

To close E1–E7 a staff member with access to the official documents must answer them; the answers then replace the OQ texts and, where
they change rules, new passages go into `corpus/verified_passages.json` and the evaluation expectations are revisited.

## B. Provider limitation (measured)

* The configured provider caps the model at **8000 tokens per minute**. One full agent run uses roughly 13k–23k tokens, so a run takes
  ~2–3 minutes and real-LLM load testing is impossible. Mitigations implemented: header-driven pacing, patient 429 retries, a run budget
  of 450 s. A higher-tier key removes the limit.
* `openai/gpt-oss-20b` repeatedly failed the research prompt (HTTP 400, native tool calls) even with the format note; the project uses
  `openai/gpt-oss-120b`. Other small models are untested.
* Real-model behaviour varies between runs; the evaluation is one sample per scenario (n = 19), not a statistical estimate.

## C. Code / scope limitations

* **No authentication or authorization.** The portal switch only changes which screens are shown. Anyone who can reach the API can submit,
  read any petition, upload and download documents and record an examiner decision (self-declared name). Do not expose beyond a trusted
  network. A real deployment needs an authenticating proxy / identity provider, per-user rights and audit logging.
* **Only attendance petitions are analysed.** Re-evaluation, re-registration, medical-leave and grade-grievance petitions always escalate
  (`unsupported_petition_type`) because their regulations are not in the corpus.
* **Uploaded documents are stored only.** They are not parsed, scanned for malware, OCR'd or checked by any agent; the declared documentation
  field is student-declared and unverified.
* Guardrails are heuristic (regex/rule based) and can both miss attacks and flag legitimate text. They are a layer, not a guarantee.
* The retrieval corpus is one 41-page PDF (197 chunks). Retrieval precision is modest (see `TESTING_REPORT.md`: context relevance ≈ 0.5);
  the verifier, not retrieval, is what prevents unsupported citations.
* No background reaper for stuck runs (a run is marked failed when read after twice the job timeout). `WORKER_MODE=simple` has no per-job
  crash isolation.
* SQLite is a single-writer store: fine for this scale, not for many API/worker replicas on different hosts.
* Student "history" is looked up by the synthetic reference typed into the browser; there is no ownership check.
* The Streamlit UI is kept as a fallback and is not redesigned further.
* Browser testing covered Chromium only (headless); Firefox/Safari and screen-reader use were not tested. A keyboard-only pass was not done
  beyond form labels, focus rings and the skip link.
* Not set up: CI, container image digests/SBOM, TLS, secret manager, data-retention policy, a stale-job reaper.

## D. Future enhancements

Authentication and per-role authorization with audit trail · examiner assignment and SLAs · OCR/virus scanning of documents (kept out of the
AI path) · more regulation sources once verified (bye-laws, revaluation) · evaluation against a human-labelled gold set · pagination and
server-side search in the queue · e-mail/notification hooks · Postgres for multi-node deployment.
