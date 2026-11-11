# Security review

**Scope:** this repository as built and run on 2026-11-08. It is a coursework prototype that handles **synthetic data only**.
**It is not production-secure**: there is **no authentication or authorization** (see §2). Detailed history of earlier reviews is in
`docs/security_review.md`; this file is the current, consolidated state.

Evidence labels: **Verified** = a command/test in this session proved it · **By design** = code/config reviewed · **Open** = not done.

## 1. Result summary

| Check | Result |
|---|---|
| Black-box probe against the running stack (`scripts/security_probe.py`, output in `docs/security_probe_results.json`) | **28 / 28 passed** |
| Secret scan (`scripts/check_no_secrets.py`) | ok (pattern-based; cannot prove absence) |
| Python tests touching security (`test_examiner.py`, `test_guardrails.py`, `test_secrets.py`, `test_observability.py`, `test_reliability.py`, `test_auth.py`) | pass (see `TESTING_REPORT.md`) |
| Frontend `npm audit` | 8 findings, **all accepted with reasons** (§6) |
| Authentication / authorization | **Implemented and Verified** (bcrypt, sessions, RBAC, isolation; see §2) |

## 2. Authentication and Role-Based Access Control — Implemented

* **Dual Login Portals**: Completely distinct login experiences for Students (`/student/login`) and Examiners (`/examiner/login`). The old demonstration role switch has been removed.
* **Secure Password Hashing**: Passwords stored using `bcrypt` (12 rounds) with salted hashing and constant-time password verification (`src/triage/auth.py`). Passwords are never stored or returned in plain text.
* **Token-Based Sessions**: Opaque session tokens (`sat_<hex>`) generated via `secrets.token_urlsafe(32)` stored in `auth_sessions` table with expiration timestamps (default 2 hours). Tokens transmitted in `Authorization: Bearer <token>` header.
* **Role-Based Access Control (RBAC)**:
  * Strict endpoint guards: `POST /v1/runs/{id}/examiner-decision` requires authenticated `examiner` role (returns HTTP 403 Forbidden for students or unauthenticated users).
  * **Attributed Decisions**: Examiner decisions automatically record the authenticated examiner's ID (`examiner_id`) and name, eliminating self-asserted free text identity.
  * **Student Privacy Isolation**: Authenticated students are restricted to their own petitions (`student_ref`). Requests attempting to access or query another student's petition are rejected with HTTP 403 Forbidden.
* **Brute-Force Rate Limiting**: Dedicated rate limiting on login endpoints (`/v1/auth/login`, `/v1/auth/student/login`, `/v1/auth/examiner/login`) capped at 15 requests per 60-second window per client IP with HTTP 429 and `Retry-After`.
* **Demonstration Credentials**: Pre-seeded only in development/demo mode (`DEMO_ACCOUNTS_ENABLED=true`):
  * Student: `STU2026001` / `Student@123`
  * Examiner: `EXM2026001` / `Examiner@123`
  * In production mode (`APP_ENV=production`), automatic demo account seeding is strictly disabled.
* **Automated Test Coverage**: 10 comprehensive security unit tests in `tests/test_auth.py` verifying login endpoints, password hashing, cross-portal rejection, 403 authorization enforcement, multi-student profile verification, student isolation, decision attribution, and session revocation. Verified with 18 unit tests in frontend (`npm test`).

## 3. Input validation and API errors

| Area | Control | Status |
|---|---|---|
| Petition body | Pydantic contract with `extra=forbid`, regexes (`SYN-######`), ranges, cross-field checks; body ≤ 64 KiB (413); invalid → 422 + quarantine, **never queued**; no stack trace in responses | Verified (probe: invalid JSON, JSON array, SQL-ish strings, wrong content type, empty body, 70 kB body, 4 MB body through nginx) |
| SQL injection | Every query parameterised; SQL-looking `student_ref` rejected and the `runs` table is intact afterwards | Verified |
| Examiner decision | Enum vocabulary distinct from the AI routes; note 10–1000 chars; run must be finished; unknown run → 404 | Verified |
| Rate limiting | `POST /v1/petitions`, `…/documents`, `…/examiner-decision` each have a per-client Redis counter. The latter two run as dependencies **before** body validation, so invalid bursts count (bug found and fixed in this session) | Verified (probe + `test_rate_limit_counts_invalid_requests_too`) |
| Error messages | Provider errors are redacted of the API key and truncated; unknown ids give plain 404 | Verified |

## 4. File upload and download

* Accepted: PDF, PNG, JPEG, **identified by magic bytes**, never by the client's file name or content type. Everything else → 415
  (probe: HTML/script disguised as `.pdf`, executable disguised as `.png`, SVG, empty file).
* Limits: 2 MiB per file (413), 3 files per petition (409), exact duplicates refused (409); nginx caps request bodies at 3 MB.
* Storage: server-chosen file name `<sha256[:24]>.<ext>` under `uploads/<run_id>/` (the run id must exist in the database); the client's name is
  sanitised and kept only as a display label. **Path traversal attempts** in the run id and document id return 404/422 (probe).
* Download: `Content-Disposition: attachment`, `X-Content-Type-Options: nosniff`, `Content-Security-Policy: default-src 'none'`.
* Files are **never parsed, rendered, scanned for malware or sent to a model** (Open: no antivirus; any real deployment needs one).
* **No access control** on download (see §2).

## 5. Prompt injection, model output and data exposure

* Petition text is untrusted data. Input guardrails (heuristic patterns: instruction override, prompt exfiltration, fake authority, abusive
  language) escalate **before any model call** (`unsafe_input`; real-model evaluation S18–S21 all escalated without a model call).
* Retrieved passages are scanned as untrusted text; a passage that reads like an instruction is withheld.
* The model has no write access: it can only call allow-listed retrieval tools with validated, bounded arguments.
* Output controls: final-decision wording filter, numeric-claim check, verbatim-citation verification, reserved-authority downgrade, no AI rejection
  inside the condonable band. Guardrails are heuristics and can miss attacks or flag legitimate text (`docs/guardrails.md`).
* Secrets: keys exist only in the private `.env` (git-ignored). The probe proved the key and the provider URL appear in **none** of `/metrics`,
  `/readyz`, `/v1/system`, `/v1/stats`, `/v1/corpus`, `/openapi.json`; `/metrics` contains no petition text. Logs/traces redact bearer tokens and
  key assignments (`test_observability.py`).
* **Data sent to the provider:** petition text (after guardrails) and retrieved regulation text go to whichever provider the operator configures.
  Synthetic data only; the provider's data-handling terms were not reviewed.
* The quarantine table stores rejected payloads verbatim (≤ 20 kB). A user who types real data into an invalid request would have it stored; purge
  with `DELETE FROM quarantine`.

## 6. Dependencies

| Component | Result |
|---|---|
| Python (`pip-audit`, earlier session, pinned requirement files) | api/ui: none; worker: 5 advisories in `chromadb==1.5.9` (no fixed release listed). Chroma has no published port and is reachable only on the Compose network; the app never sends it a user-controlled model repository. Accepted residual risk. `pip-audit` was **not re-run** in this session (not installed). |
| Frontend `npm audit` (8 findings) | **Dev-tooling only (not shipped):** `vite` (dev-server path traversal), `vitest` / `@vitest/mocker` / `vite-node` / `tinypool` / `esbuild` (test-runner and dev-server issues). The production image contains only the static build served by nginx. **Runtime:** `react-router(-dom)` – an SSR-hydration issue and an open-redirect via a backslash in `<Link>`; the app is client-side only (no SSR) and all links are built from fixed paths plus ids returned by our own API. The only fix is a major upgrade (v7), deferred to avoid destabilising the UI. |
| Base images | `python:3.11-slim`, `redis:7-alpine`, `node:22-alpine`, `nginx:1.27-alpine` float within their tags (Open: pin by digest). |

## 7. Container and network

* api/worker/ingest/ui run as a non-root user (uid 1000). The `web` container runs the stock nginx image (master as root, workers unprivileged).
* Host ports bind to `127.0.0.1` only: 8080 (web), 8000 (api), 8501 (ui), and the observability ports when that profile is on.
* Security headers on the web app: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` (bug found by the probe:
  nginx dropped them in locations that set their own `add_header`; fixed and re-verified). **No CSP or HSTS on the SPA and no TLS** (Open).
* CORS is **off by default** (same-origin proxy). `CORS_ORIGINS` enables an explicit allow-list only; `*` is never used (probe verified no CORS header
  for an arbitrary origin).
* cAdvisor runs privileged (needed for cgroup metrics) – the reason observability is an opt-in profile. Grafana's default admin password is `admin`
  unless `GRAFANA_ADMIN_PASSWORD` is set (Open for anything but a local demo).

## 8. Reliability as a security property

Provider failure, malformed model output, retrieval failure, budget exhaustion and open circuit breaker all end in an **escalation with no
determination and no citations** – never a fabricated answer (`SYSTEM_TESTING_REPORT.md` §4).

## 9. Findings fixed in this session

1. Rate limiting did not apply to requests that failed body validation on the decision/upload endpoints → now a pre-validation dependency.
2. nginx dropped its security headers on locations that set their own `add_header` → repeated per location.
3. Provider error bodies were discarded; now surfaced redacted (diagnosis without leaking the key).
4. Petition submission accepted arbitrarily large bodies → capped at 64 KiB.
5. The model could recommend **rejection** inside the band where the regulation reserves the decision to the Vice-Chancellor → blocked by a deterministic guard
   and converted to a referral with a visible system note.

## 10. Not done

Authentication/authorization · antivirus / content disarm for uploads · TLS and HSTS · CSP for the SPA · secret manager · image digests / SBOM ·
CI with scheduled audits · retention policy · penetration test by an independent party.
