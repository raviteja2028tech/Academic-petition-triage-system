> **Superseded (2026-11-08).** The current consolidated review is `SECURITY_REVIEW.md` in the repository root. This file is kept as the earlier record.

# Security and dependency review (Phase 8)

Scope: this repository as of the review date (2026-10-28). It is a coursework prototype for **synthetic data**, not a hardened production service. Items are
marked **Verified** (checked by a command or test in this session), **By design** (code/config reviewed), or **Open**.

## Secrets and data
| Item | Status |
|---|---|
| No credentials in the repo; configuration only from environment variables; `.env` and `*.env` ignored, `.env.example` holds blanks/placeholders | Verified — `python scripts/check_no_secrets.py`: ok (119 files). The scan is pattern-based and cannot prove absence. |
| Logs/traces never contain petition text or credentials | Verified by tests (`test_observability.py`): redaction of bearer tokens, `sk-` keys, key assignments and the literal configured key; petition fields dropped; span attributes filtered. |
| Real student data | None used. `student_ref` must match `^SYN-\d{6}$`; the API rejects anything else and quarantines the payload. **Note:** the quarantine table stores the raw rejected payload (≤ 20 kB) so a user who types real data into a malformed request would have it stored — covered by the "synthetic data only" notices; purge with `DELETE FROM quarantine`. |
| Git hygiene | The Git repository that contains this folder is rooted at the user's home directory (all of `C:\Users\ravit` shows as untracked). **Do not run `git add .` from there.** Create a separate repository for this project before pushing (nothing was committed or pushed). |

## Dependencies
| Item | Status |
|---|---|
| Python packages pinned with `==` in `requirements-*.txt`; OpenTelemetry pinned to 1.45.1 | Verified |
| `pip-audit` (throwaway venv, `--no-deps` on the pinned files) | api: **no known vulnerabilities**; ui: **none**; worker: **5 advisories in `chromadb==1.5.9`** (below) |
| Container base images: `python:3.11-slim`, `redis:7-alpine` float within a major/minor line; `chromadb/chroma:1.5.9`, Prometheus, Grafana, Jaeger, cAdvisor pinned to exact tags | By design — floating bases are an Open item (pin by digest before any real deployment). Image tags verified to exist (`docker manifest inspect`). |
| Python 3.11 in containers; tests ran on 3.14 on the host | Open — CI on 3.11 not set up |

### chromadb 1.5.9 advisories (Open, accepted residual risk)
PYSEC-2026-311 / CVE-2026-45829 (pre-authentication code injection through the Chroma **server's** collections endpoint with a malicious model repository and `trust_remote_code`),
PYSEC-2026-3814 / CVE-2026-45833 (same class, authenticated), PYSEC-2026-3815 / CVE-2026-45831 and PYSEC-2026-3813 / CVE-2026-45830 (RBAC authorization providers; **not used** here).
No fixed versions were listed by the audit database. **Exposure in this deployment:** the `chroma` service has no published port and is reachable only from other containers on the Compose
network; the application never sends a user-controlled model repository to Chroma (it embeds locally and passes vectors). Residual risk: a compromised container on the same network could
exploit it. Action: re-run the audit before release and upgrade as soon as a fixed release exists. (Incident log #5.)

## Container and network hardening
| Item | Status |
|---|---|
| api, worker, ingest, ui, locust run as non-root user `app` (uid 1000) | Verified (Dockerfiles) |
| Published ports bound to `127.0.0.1` (api 8000, ui 8501; observability: 16686, 9090, 8081, 3000); redis/chroma publish nothing | Verified (`docker-compose.yml`) |
| cAdvisor runs `privileged` with host mounts | By design — needed for cgroup metrics; the reason the observability stack is an opt-in profile |
| Grafana admin password defaults to `admin` | Open — local demo only; override `GRAFANA_ADMIN_PASSWORD` in `.env`; anonymous access disabled |
| Read-only mounts for corpus, eval, dashboards | By design |
| No `--privileged`, docker.sock mounts or host networking in the default stack | Verified |

## Application
| Item | Status |
|---|---|
| **No authentication or authorization** on the API or UI. `X-Client-Id` is self-asserted, so the per-client rate limit can be evaded by changing the header. | **Open — by design for a prototype.** Put behind an authenticating proxy before any shared use. |
| SQL injection | By design — all queries parameterised. |
| Input validation | Pydantic with `extra=forbid`, regexes, ranges, cross-field checks; invalid input is quarantined and never queued. No explicit request-body size cap beyond field limits (uvicorn/ASGI defaults) — Open. |
| Prompt injection / unsafe output | Heuristic guardrails + structural controls (`docs/guardrails.md`); explicitly not a guarantee. |
| LLM provider traffic | Petition text (after guardrails) is sent to whichever provider the operator configures. Operator responsibility to choose a provider permitted for this data; synthetic data only. |
| Error messages | Configuration errors are explicit (missing LLM, missing `EMBED_MODEL`, unreachable Chroma) and expose no secrets; exceptions are logged as type + message. |
| Denial of service | Rate limit, bounded steps/tool calls/time per run, job timeout 300 s, bounded retries. No global concurrency cap on the API. |

## Recommended before any real deployment
Authentication and per-user identity; TLS termination; secret manager; image digests and SBOM; CI running tests + `pip-audit` + secret scan; request-size limits; a stale-run reaper;
data-retention policy for runs/quarantine; legal review of the corpus source and redistribution terms (still unresolved — `corpus/SOURCES.md`).
