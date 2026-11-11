"""FastAPI application: validation + quarantine at the boundary, queueing, status, health, corpus status."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import uuid
from typing import Callable, Optional

import httpx
import redis
from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import ValidationError
from rq import Queue

from .. import auth, db
from ..config import Settings, get_settings
from ..contracts import (CorpusStatus, ExaminerDecisionAccepted, ExaminerDecisionIn, FeedbackAccepted, FeedbackIn, FieldError, Health,
                         LoginRequest, LoginResponse, LogoutResponse, PetitionAccepted, PetitionRequest, RunList,
                         RunStatus, RunView, UserRole, UserView, ValidationErrorResponse)

from ..observability import (configure_logging, current_traceparent, get_correlation_id, new_correlation_id,
                             set_context, setup_tracing, span)
from ..observability.trace import build_trace
from ..reliability.deps import mark_redis_down, redis_recently_down
from ..reliability.metrics import Metrics
from ..reliability.ratelimit import check_rate

STALE_FLOOR_SECONDS = 240  # a run 'running' longer than (job timeout + 2 min, at least this) lost its worker

TASK_PATH = "triage.worker.tasks.process_petition"

MAX_PETITION_BODY_BYTES = 64 * 1024
MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_DOCS_PER_RUN = 3
_SIGNATURES = ((b"%PDF-", "pdf", "application/pdf"), (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
               (b"\xff\xd8\xff", "jpg", "image/jpeg"))


def sniff_upload(data: bytes):
    """Type by CONTENT (magic bytes), never by the client-supplied name or content type. None = not allowed."""
    for sig, ext, ctype in _SIGNATURES:
        if data.startswith(sig):
            return ext, ctype
    return None


def clean_filename(name: str) -> str:
    base = os.path.basename(name.replace("\\", "/"))
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", base)[:80].strip(" .")
    return base or "document"

# Verified (see docs/corpus_verification.md) status of the assignment's difficult case.
DIFFICULT_CASE_STATUS = "PARTIALLY_VERIFIED"


WORKER_ALIVE_SECONDS = 90   # workers run with worker_ttl=60, so a live one heartbeats at least every ~45 s


def live_worker_count(conn) -> int:
    """Workers whose heartbeat is recent. RQ keeps a stopped/killed worker registered for minutes, which made readiness report
    workers that were not there (found by the worker-down drill)."""
    from datetime import datetime, timezone
    from rq import Worker
    now = datetime.now(timezone.utc)
    n = 0
    for w in Worker.all(connection=conn):
        hb = w.last_heartbeat
        if hb is not None:
            hb = hb if hb.tzinfo else hb.replace(tzinfo=timezone.utc)
            if (now - hb).total_seconds() <= WORKER_ALIVE_SECONDS:
                n += 1
    return n


def stale_after_seconds(s: Settings) -> float:
    """A run 'running' longer than this lost its worker: the RQ job timeout (run budget + 60 s) plus 2 minutes, never below 4 min."""
    return max(STALE_FLOOR_SECONDS, int(s.max_run_seconds) + 60 + 120)


def _field_errors(exc: ValidationError) -> list[dict]:
    errs = []
    for e in exc.errors():
        loc = ".".join(str(p) for p in e["loc"]) or "(request)"
        errs.append({"field": loc, "rule": e["type"], "message": e["msg"]})
    return errs


def create_app(settings_factory: Callable[[], Settings] = get_settings,
               redis_factory: Optional[Callable[[Settings], redis.Redis]] = None,
               queue_factory: Optional[Callable[[Settings, redis.Redis], Queue]] = None) -> FastAPI:
    app = FastAPI(
        title="Academic Petition Triage API",
        version="0.2.0",
        description=("Accepts SYNTHETIC student petitions, validates them, and processes them asynchronously. "
                     "Phase 1/2: processing is a labelled PLACEHOLDER; no regulation-based determination is made. "
                     "The system never decides a petition; an examination officer does."),
    )

    origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
    if origins:   # explicit allow-list only; never "*"
        from fastapi.middleware.cors import CORSMiddleware
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"],
                           allow_headers=["content-type", "x-client-id", "x-correlation-id", "authorization"], max_age=600)

    # Seed demo accounts if enabled (development/demonstration mode)
    try:
        s0 = settings_factory()
        if s0.demo_accounts_enabled and not auth.is_production():
            auth.seed_demo_accounts(s0.db_path)
    except Exception:
        pass

    @app.middleware("http")
    async def observe(request: Request, call_next):
        """Correlation id (accepted or generated) + request span + request metrics. Never logs bodies."""
        corr = request.headers.get("x-correlation-id") or new_correlation_id()
        set_context(correlation_id=corr[:64])
        t0 = time.time()
        status = 500
        with span("http.request", **{"http.method": request.method}) as sp:
            try:
                response = await call_next(request)
                status = response.status_code
                response.headers["X-Correlation-ID"] = corr[:64]
                return response
            finally:
                route = request.scope.get("route")
                tmpl = getattr(route, "path", "unmatched")
                if sp is not None:
                    sp.update_name(f"{request.method} {tmpl}")
                    sp.set_attribute("http.route", tmpl)
                    sp.set_attribute("http.status_code", status)
                try:
                    def _record() -> None:
                        m = Metrics(get_redis())
                        m.inc("http_requests_total", method=request.method, route=tmpl, status=status)
                        m.observe("http_request_seconds", time.time() - t0, route=tmpl)
                    if not redis_recently_down():
                        await run_in_threadpool(_record)
                except Exception:  # noqa: BLE001
                    pass
                if tmpl not in ("/healthz", "/readyz", "/metrics"):
                    logging.getLogger("triage.api").info("request", extra={
                        "method": request.method, "route": tmpl, "status": status, "duration_ms": int((time.time() - t0) * 1000)})

    def get_redis() -> redis.Redis:
        s = settings_factory()
        return redis_factory(s) if redis_factory else redis.Redis.from_url(s.redis_url, socket_connect_timeout=2, socket_timeout=2)

    def rate_dependency(bucket: str):
        """Per-client limit for the upload / decision endpoints, as a FastAPI dependency so it runs before the request body
        is validated (invalid bursts count too). Fails open if the limiter itself is unavailable."""
        def dep(request: Request, x_client_id: Optional[str] = Header(default=None)) -> None:
            s = settings_factory()
            if not s.rate_limit_enabled:
                return
            key = f"{bucket}:{(x_client_id or (request.client.host if request.client else 'anonymous'))[:64]}"
            try:
                if redis_recently_down():
                    return
                conn_rl = get_redis()
                d = check_rate(conn_rl, key, s.rate_limit_requests, s.rate_limit_window_seconds)
            except Exception:  # noqa: BLE001
                mark_redis_down()
                return
            if not d.allowed:
                Metrics(conn_rl).inc("rate_limited_total")
                raise HTTPException(429, f"Rate limit exceeded; retry in {d.retry_after}s.", headers={"Retry-After": str(d.retry_after)})
        return dep

    def auth_rate_dependency(request: Request, x_client_id: Optional[str] = Header(default=None)) -> None:
        s = settings_factory()
        if not s.rate_limit_enabled:
            return
        key = f"auth:{(x_client_id or (request.client.host if request.client else 'anonymous'))[:64]}"
        try:
            if redis_recently_down():
                return
            conn_rl = get_redis()
            d = check_rate(conn_rl, key, s.auth_rate_limit_requests, s.auth_rate_limit_window_seconds)
        except Exception:  # noqa: BLE001
            mark_redis_down()
            return
        if not d.allowed:
            Metrics(conn_rl).inc("rate_limited_total")
            raise HTTPException(429, f"Login rate limit exceeded; retry in {d.retry_after}s.", headers={"Retry-After": str(d.retry_after)})

    def get_current_user_optional(request: Request, authorization: Optional[str] = Header(default=None)) -> Optional[dict]:
        if not authorization or not authorization.lower().startswith("bearer "):
            return None
        token = authorization[7:].strip()
        s = settings_factory()
        user = auth.authenticate_token(s.db_path, token)
        if not user:
            raise HTTPException(401, "Session expired or invalid authentication token")
        return user

    def require_authenticated_user(user: Optional[dict] = Depends(get_current_user_optional)) -> dict:
        if not user:
            raise HTTPException(401, "Authentication required")
        return user

    def require_role(allowed_roles: list[str]):
        def dep(user: Optional[dict] = Depends(get_current_user_optional)) -> Optional[dict]:
            s = settings_factory()
            if not user:
                if s.auth_enforce_strict:
                    raise HTTPException(401, "Authentication required")
                return None
            if user["role"] not in allowed_roles:
                raise HTTPException(403, f"Access forbidden: role '{user['role']}' is not authorized for this resource")
            return user
        return dep

    def get_queue(conn: redis.Redis) -> Queue:
        s = settings_factory()
        return queue_factory(s, conn) if queue_factory else Queue(s.queue_name, connection=conn)

    # ---------------- ops ----------------
    @app.get("/healthz", response_model=Health, tags=["ops"])
    def healthz() -> Health:
        return Health(status="alive")

    @app.get("/readyz", response_model=Health, tags=["ops"])
    def readyz():
        s = settings_factory()
        checks: dict[str, str] = {}
        redis_ok = False
        if redis_recently_down():
            checks["redis"] = "down: recently unreachable"
        else:
            try:
                get_redis().ping()
                checks["redis"] = "ok"
                redis_ok = True
            except Exception as e:  # noqa: BLE001
                mark_redis_down()
                checks["redis"] = f"down: {type(e).__name__}"
        try:
            db.check(s.db_path)
            checks["database"] = "ok"
        except Exception as e:  # noqa: BLE001
            checks["database"] = f"down: {type(e).__name__}"
        checks["chroma"] = "ok" if _chroma_reachable(s) else ("down" if s.chroma_host else "not-configured")
        degraded = []
        if redis_ok:
            try:
                n = live_worker_count(get_redis())
                checks["workers"] = str(n)
                if n == 0:
                    degraded.append("no_workers")
            except Exception:  # noqa: BLE001
                checks["workers"] = "unknown"
        else:
            checks["workers"] = "unknown"
            degraded.append("redis_down: petitions cannot be queued")
        checks["llm"] = "configured" if (s.llm_base_url and s.llm_model) else "not-configured"
        if checks["llm"] != "configured":
            degraded.append("llm_not_configured: petitions escalate with reason llm_unavailable")
        if checks["chroma"] == "down":
            degraded.append("chroma_down: retrieval unavailable")
        try:
            if not redis_ok:
                raise RuntimeError("redis down")
            from ..reliability.breaker import CircuitBreaker
            checks["llm_breaker"] = CircuitBreaker(get_redis(), "primary").state
            if checks["llm_breaker"] != "closed":
                degraded.append("llm_circuit_" + checks["llm_breaker"])
        except Exception:  # noqa: BLE001
            checks["llm_breaker"] = "unknown"
        checks["degraded"] = "; ".join(degraded) or "none"
        ready = checks["redis"] == "ok" and checks["database"] == "ok"
        body = Health(status="ready" if ready else "not-ready", checks=checks)
        return JSONResponse(body.model_dump(), status_code=200 if ready else 503)

    @app.get("/v1/system", tags=["ops"])
    def system_overview():
        """Live queue / worker / provider snapshot for the monitoring page. Every field is read from Redis or settings."""
        s = settings_factory()
        out: dict = {"llm": {"configured": bool(s.llm_base_url and s.llm_model), "model": s.llm_model or None,
                             "fallback_configured": bool(s.fallback_llm_base_url and s.fallback_llm_model)},
                     "limits": {"max_run_seconds": s.max_run_seconds, "llm_timeout_seconds": s.llm_timeout_seconds,
                                "rate_limit_requests": s.rate_limit_requests, "rate_limit_window_seconds": s.rate_limit_window_seconds,
                                "cache_enabled": s.cache_enabled}}
        try:
            from rq import Worker
            from rq.registry import FailedJobRegistry, StartedJobRegistry
            conn = get_redis()
            q = get_queue(conn)
            out["queue"] = {"name": q.name, "queued": q.count, "started": StartedJobRegistry(queue=q).count,
                            "failed_jobs": FailedJobRegistry(queue=q).count, "workers": live_worker_count(conn)}
            from ..reliability.breaker import CircuitBreaker
            out["llm"]["breaker"] = CircuitBreaker(conn, "primary").state
        except Exception as e:  # noqa: BLE001
            out["queue"] = {"error": f"unavailable: {type(e).__name__}"}
        out["retrieval"] = {"chroma_reachable": _chroma_reachable(s) if s.chroma_host else False}
        return out

    @app.get("/metrics", response_class=PlainTextResponse, tags=["ops"])
    def metrics_endpoint():
        """Prometheus text format: counters/histograms written by API and workers into Redis."""
        try:
            m = Metrics(get_redis())
            body = m.render_prometheus()
            s = settings_factory()
            counts, _, _ = db.list_runs(s.db_path, 1)
            body += "# TYPE runs_in_state gauge\n" + "".join(
                f'runs_in_state{{status="{k}"}} {v}\n' for k, v in sorted(counts.items()))
            conn = get_redis()
            try:
                from rq import Worker
                body += f"# TYPE queue_depth gauge\nqueue_depth {get_queue(conn).count}\n"
                body += f"# TYPE workers_active gauge\nworkers_active {Worker.count(connection=conn)}\n"
            except Exception:  # noqa: BLE001
                pass
            from ..reliability.breaker import CircuitBreaker
            states = {"closed": 0, "half_open": 1, "open": 2}
            body += "# TYPE llm_breaker_state gauge\n" + "".join(
                f'llm_breaker_state{{provider="{n}"}} {states[CircuitBreaker(conn, n).state]}\n'
                for n in ("primary", "fallback"))
            return body
        except Exception as e:  # noqa: BLE001
            raise HTTPException(503, f"metrics unavailable: {type(e).__name__}")

    # ---------------- auth ----------------
    @app.post("/v1/auth/login", response_model=LoginResponse, tags=["auth"],
              dependencies=[Depends(auth_rate_dependency)])
    def auth_login(body: LoginRequest):
        s = settings_factory()
        user = auth.authenticate_user(
            s.db_path,
            user_id=body.user_id,
            password=body.password,
            expected_role=body.role.value if body.role else None,
        )
        if not user:
            raise HTTPException(401, "Invalid credentials or unauthorized role")
        sess = auth.create_user_session(s.db_path, user, s.auth_token_expire_seconds)
        return LoginResponse(**sess)

    @app.post("/v1/auth/student/login", response_model=LoginResponse, tags=["auth"],
              dependencies=[Depends(auth_rate_dependency)])
    def auth_student_login(body: LoginRequest):
        s = settings_factory()
        user = auth.authenticate_user(s.db_path, user_id=body.user_id, password=body.password, expected_role="student")
        if not user:
            raise HTTPException(401, "Invalid Student ID or password")
        sess = auth.create_user_session(s.db_path, user, s.auth_token_expire_seconds)
        return LoginResponse(**sess)

    @app.post("/v1/auth/examiner/login", response_model=LoginResponse, tags=["auth"],
              dependencies=[Depends(auth_rate_dependency)])
    def auth_examiner_login(body: LoginRequest):
        s = settings_factory()
        user = auth.authenticate_user(s.db_path, user_id=body.user_id, password=body.password, expected_role="examiner")
        if not user:
            raise HTTPException(401, "Invalid Examiner ID or password")
        sess = auth.create_user_session(s.db_path, user, s.auth_token_expire_seconds)
        return LoginResponse(**sess)

    @app.post("/v1/auth/logout", response_model=LogoutResponse, tags=["auth"])
    def auth_logout(authorization: Optional[str] = Header(default=None)):
        s = settings_factory()
        if authorization and authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
            auth.logout_session(s.db_path, token)
        return LogoutResponse(message="Logged out successfully", success=True)

    @app.get("/v1/auth/me", response_model=UserView, tags=["auth"])
    def auth_me(user: dict = Depends(require_authenticated_user)):
        return UserView(**user)

    @app.get("/v1/auth/demo-credentials", tags=["auth"])
    def auth_demo_credentials():
        s = settings_factory()
        if not s.demo_accounts_enabled or auth.is_production():
            raise HTTPException(404, "Demo accounts are not available in production")
        return {
            "enabled": True,
            "student": {"id": auth.DEMO_STUDENT_ID, "password": auth.DEMO_STUDENT_PASSWORD, "name": auth.DEMO_STUDENT_NAME},
            "examiner": {"id": auth.DEMO_EXAMINER_ID, "password": auth.DEMO_EXAMINER_PASSWORD, "name": auth.DEMO_EXAMINER_NAME},
            "students": [
                {"id": s_item["id"], "password": s_item["password"], "name": s_item["name"],
                 "branch": s_item.get("branch"), "semester": s_item.get("semester"), "usn": s_item.get("usn")}
                for s_item in auth.DEMO_STUDENTS
            ],
            "examiners": [
                {"id": e_item["id"], "password": e_item["password"], "name": e_item["name"],
                 "title": e_item.get("title", "Official Examiner")}
                for e_item in auth.DEMO_EXAMINERS
            ],
        }

    # ---------------- petitions ----------------
    @app.post("/v1/petitions", status_code=202, response_model=PetitionAccepted,
              responses={422: {"model": ValidationErrorResponse}, 503: {"description": "queue unavailable"}},
              tags=["petitions"])
    async def submit_petition(request: Request, x_client_id: Optional[str] = Header(default=None),
                              x_correlation_id: Optional[str] = Header(default=None)):
        s = settings_factory()
        if s.rate_limit_enabled:
            client_key = x_client_id or (request.client.host if request.client else "anonymous")
            try:
                if redis_recently_down():
                    raise ConnectionError("redis recently down")
                conn_rl = get_redis()
                d = check_rate(conn_rl, client_key[:64], s.rate_limit_requests, s.rate_limit_window_seconds)
            except Exception:  # noqa: BLE001  (limiter unavailable: fail open, but the queue check below still applies)
                mark_redis_down()
                d = None
            if d is not None and not d.allowed:
                Metrics(conn_rl).inc("rate_limited_total")
                return JSONResponse(
                    {"detail": f"Rate limit exceeded: {d.limit} petitions per {s.rate_limit_window_seconds}s per "
                               f"client. Retry in {d.retry_after}s.", "retry_after_seconds": d.retry_after},
                    status_code=429,
                    headers={"Retry-After": str(d.retry_after), "X-RateLimit-Limit": str(d.limit),
                             "X-RateLimit-Remaining": "0"})
        raw = await request.body()
        if len(raw) > MAX_PETITION_BODY_BYTES:
            return JSONResponse({"detail": f"request body too large (max {MAX_PETITION_BODY_BYTES // 1024} KiB)"}, status_code=413)
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("body must be a JSON object")
            petition = PetitionRequest.model_validate(payload)
        except (ValueError, ValidationError) as exc:  # json errors and pydantic errors are both ValueError
            if isinstance(exc, ValidationError):
                errors = _field_errors(exc)
            else:
                errors = [{"field": "(body)", "rule": "invalid_json", "message": str(exc)[:200]}]
            qid = db.quarantine(s.db_path, payload if "payload" in locals() else raw.decode("utf-8", "replace"),
                                errors, x_client_id)
            return JSONResponse(ValidationErrorResponse(quarantine_id=qid,
                                                        errors=[FieldError(**e) for e in errors]).model_dump(),
                                status_code=422)

        corr = get_correlation_id() or x_correlation_id or uuid.uuid4().hex
        try:
            if redis_recently_down():
                raise ConnectionError("redis recently unreachable")
            conn = get_redis()
            conn.ping()
            queue = get_queue(conn)
        except Exception as e:  # noqa: BLE001
            mark_redis_down()
            raise HTTPException(503, f"queue unavailable: {type(e).__name__}")
        run_id = db.create_run(s.db_path, json.loads(petition.model_dump_json()), x_client_id, corr)
        try:
            queue.enqueue(TASK_PATH, run_id, current_traceparent(), job_id=run_id, job_timeout=int(s.max_run_seconds) + 60)
        except Exception as e:  # noqa: BLE001
            db.set_status(s.db_path, run_id, RunStatus.failed.value, error=f"enqueue failed: {type(e).__name__}")
            raise HTTPException(503, "queue unavailable; run recorded as failed")
        return PetitionAccepted(run_id=run_id, status=RunStatus.queued, status_url=f"/v1/runs/{run_id}")

    @app.get("/v1/runs/{run_id}", response_model=RunView, tags=["petitions"])
    def get_run(run_id: str, user: Optional[dict] = Depends(get_current_user_optional)):
        s = settings_factory()
        r = db.get_run(s.db_path, run_id)
        if not r:
            raise HTTPException(404, "run not found")
        if user and user["role"] == "student":
            pet_ref = (r["petition"] or {}).get("student_ref")
            if pet_ref and pet_ref != user["user_id"] and pet_ref != user.get("usn"):
                raise HTTPException(403, "Access denied: students can only access their own petitions")
        if r["status"] == "running" and db.fail_if_stale(s.db_path, run_id, stale_after_seconds(s)):
            r = db.get_run(s.db_path, run_id)
        return RunView(run_id=r["run_id"], status=r["status"], created_at=r["created_at"], updated_at=r["updated_at"],
                       petition_type=r["petition"].get("petition_type"), student_ref=r["petition"].get("student_ref"),
                       mode=r["mode"], result=r["result"], error=r["error"], events=r["events"],
                       petition=r["petition"], examiner_decisions=db.list_examiner_decisions(s.db_path, run_id),
                       documents=db.list_documents(s.db_path, run_id))

    @app.get("/v1/runs", response_model=RunList, tags=["petitions"])
    def list_runs(limit: int = 20, status: Optional[str] = None, student_ref: Optional[str] = None,
                  petition_type: Optional[str] = None, offset: int = 0, real_only: bool = False,
                  awaiting_decision: Optional[bool] = None,
                  user: Optional[dict] = Depends(get_current_user_optional)):
        s = settings_factory()
        effective_student_ref = student_ref
        if user and user["role"] == "student":
            effective_student_ref = user["user_id"]
        counts, runs, matched = db.list_runs(s.db_path, max(1, min(limit, 200)), status, effective_student_ref, petition_type, max(0, offset),
                                             real_only, awaiting_decision)
        latest = db.latest_decisions(s.db_path, [r["run_id"] for r in runs])
        return RunList(counts=counts, matched=matched,
                       runs=[{**r, "examiner_decision": (latest.get(r["run_id"]) or {}).get("decision")} for r in runs])

    # ---------------- human examiner decision (separate from the AI recommendation) ----------------
    @app.post("/v1/runs/{run_id}/examiner-decision", response_model=ExaminerDecisionAccepted, status_code=201,
              tags=["examiner"], dependencies=[Depends(rate_dependency("decision"))])
    def post_examiner_decision(run_id: str, body: ExaminerDecisionIn,
                               user: Optional[dict] = Depends(require_role(["examiner"]))):
        """Records a human examiner's decision next to (never instead of) the AI recommendation.
        If authenticated as examiner, attributes the decision directly to the authenticated examiner account."""
        s = settings_factory()
        r = db.get_run(s.db_path, run_id)
        if not r:
            raise HTTPException(404, "run not found")
        if r["status"] not in ("completed", "escalated", "failed"):
            raise HTTPException(409, "the AI pipeline has not finished; wait for the recommendation before deciding")
        res = r["result"] or {}
        snap = {"status": r["status"], "route": res.get("route"), "position": res.get("position"),
                "escalation_reason": (res.get("escalation") or {}).get("reason"),
                "citations": [f"{c.get('clause_id')} p.{c.get('page')}" for c in res.get("citations", [])],
                "llm_models": res.get("llm_models")}
        examiner_label = user["name"] if user else body.examiner_label
        did = db.add_examiner_decision(s.db_path, run_id, examiner_label, body.decision.value, body.note, snap)
        return ExaminerDecisionAccepted(run_id=run_id, decision_id=did)

    # ---------------- supporting documents (stored for the examiner; never parsed or sent to a model) ----------------
    @app.post("/v1/runs/{run_id}/documents", status_code=201, tags=["petitions"],
              dependencies=[Depends(rate_dependency("upload"))])
    async def upload_document(run_id: str, file: UploadFile = File(...),
                              user: Optional[dict] = Depends(get_current_user_optional)):
        s = settings_factory()
        r = db.get_run(s.db_path, run_id)
        if not r:
            raise HTTPException(404, "run not found")
        if user and user["role"] == "student":
            pet_ref = (r["petition"] or {}).get("student_ref")
            if pet_ref and pet_ref != user["user_id"]:
                raise HTTPException(403, "Access denied: cannot upload documents to another student's petition")
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"file too large (max {MAX_UPLOAD_BYTES // 1024} KiB)")
        kind = sniff_upload(data)
        if kind is None:
            raise HTTPException(415, "unsupported file type: only PDF, PNG and JPEG are accepted (checked by content)")
        if len(db.list_documents(s.db_path, run_id)) >= MAX_DOCS_PER_RUN:
            raise HTTPException(409, f"at most {MAX_DOCS_PER_RUN} documents per petition")
        ext, ctype = kind
        digest = hashlib.sha256(data).hexdigest()
        folder = os.path.join(os.path.dirname(os.path.abspath(s.db_path)), "uploads", run_id)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{digest[:24]}.{ext}")          # server-chosen name; the client name is display-only
        with open(path, "wb") as fh:
            fh.write(data)
        shown = clean_filename(file.filename or f"document.{ext}")
        did = db.add_document(s.db_path, run_id, shown, ctype, len(data), digest, path)
        if did is None:
            raise HTTPException(409, "this exact file is already attached")
        return {"run_id": run_id, "document_id": did, "filename": shown, "content_type": ctype, "size": len(data),
                "sha256": digest, "note": "Stored for the examiner. Not read, parsed or checked by the AI agents."}

    @app.get("/v1/runs/{run_id}/documents/{doc_id}", tags=["petitions"])
    def download_document(run_id: str, doc_id: int, user: Optional[dict] = Depends(get_current_user_optional)):
        s = settings_factory()
        r = db.get_run(s.db_path, run_id)
        if not r:
            raise HTTPException(404, "run not found")
        if user and user["role"] == "student":
            pet_ref = (r["petition"] or {}).get("student_ref")
            if pet_ref and pet_ref != user["user_id"]:
                raise HTTPException(403, "Access denied: students can only download documents from their own petitions")
        d = db.get_document(s.db_path, run_id, doc_id)
        if not d or not os.path.isfile(d["path"]):
            raise HTTPException(404, "document not found")
        return FileResponse(d["path"], media_type=d["content_type"], filename=d["filename"],
                            headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'"})

    @app.get("/v1/runs/{run_id}/trace", tags=["petitions"])
    def run_trace(run_id: str):
        """Reconstructs the run (agents, LLM calls, retrieval history, retries) from persisted run_events."""
        s = settings_factory()
        r = db.get_run(s.db_path, run_id)
        if not r:
            raise HTTPException(404, "run not found")
        return build_trace(r)

    @app.get("/v1/evaluation", tags=["evaluation"])
    def evaluation_results():
        """Latest evaluation reports found in EVAL_RESULTS_DIR, labelled by mode (scripted vs real)."""
        d = settings_factory().eval_results_dir
        out = []
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                if f.endswith(".json") and not f.startswith("experiment"):
                    try:
                        rep = json.load(open(os.path.join(d, f), encoding="utf8"))
                        out.append({"file": f, "meta": rep["meta"], "metrics": rep["metrics"], "llm_judge": rep.get("llm_judge"),
                                    "by_category": rep.get("by_category")})
                    except Exception:  # noqa: BLE001
                        continue
        exp = os.path.join(d, "experiment_second_query.json")
        experiment = json.load(open(exp, encoding="utf8")) if os.path.isfile(exp) else None
        return {"reports": out, "experiment": ({"meta": experiment["meta"], "summary": experiment["summary"]} if experiment else None)}

    @app.post("/v1/runs/{run_id}/feedback", response_model=FeedbackAccepted, tags=["feedback"])
    def post_feedback(run_id: str, body: FeedbackIn, x_client_id: Optional[str] = Header(default=None)):
        s = settings_factory()
        r = db.get_run(s.db_path, run_id)
        if not r:
            raise HTTPException(404, "run not found")
        if r["status"] not in ("completed", "escalated", "failed"):
            raise HTTPException(409, "feedback can only be given once the run has finished")
        db.upsert_feedback(s.db_path, run_id, (x_client_id or "anonymous")[:64], body.rating,
                           body.agrees_with_recommendation, body.comment)
        return FeedbackAccepted(run_id=run_id)

    @app.get("/v1/feedback", tags=["feedback"])
    def get_feedback(limit: int = 50):
        s = settings_factory()
        return {"stats": db.feedback_stats(s.db_path), "recent": db.list_feedback(s.db_path, max(1, min(limit, 200)))}

    @app.get("/v1/stats", tags=["ops"])
    def stats(real_only: bool = False):
        """Outcome, escalation, latency, token and ESTIMATED cost statistics + feedback satisfaction.
        real_only=true drops runs answered by stub/scripted models (e.g. load tests)."""
        s = settings_factory()
        return {**db.run_stats(s.db_path, real_only=real_only), "feedback": db.feedback_stats(s.db_path)}

    @app.get("/v1/stats/agents", tags=["ops"])
    def stats_agents(real_only: bool = False):
        """Per-agent executions / failures / latency from persisted run events (no invented numbers)."""
        return db.agent_stats(settings_factory().db_path, real_only=real_only)

    @app.get("/v1/quarantine", tags=["petitions"])
    def get_quarantine(limit: int = 50):
        return db.list_quarantine(settings_factory().db_path, max(1, min(limit, 200)))

    # ---------------- corpus ----------------
    @app.get("/v1/corpus", response_model=CorpusStatus, tags=["corpus"])
    def corpus_status() -> CorpusStatus:
        return build_corpus_status(settings_factory())

    return app


def _chroma_reachable(s: Settings) -> bool:
    if not s.chroma_host:
        return False
    try:
        r = httpx.get(f"http://{s.chroma_host}:{s.chroma_port}/api/v2/heartbeat", timeout=2)
        return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False


def build_corpus_status(s: Settings) -> CorpusStatus:
    sources: list[str] = []
    for root in (s.corpus_dir, os.path.join(s.corpus_dir, "raw")):
        if os.path.isdir(root):
            sources += sorted(f for f in os.listdir(root) if f.lower().endswith(".pdf"))
    reachable = _chroma_reachable(s)
    try:
        last_ok = db.last_ingest(s.db_path, only_success=True)
        last_any = db.last_ingest(s.db_path)
    except Exception:  # noqa: BLE001
        last_ok = last_any = None

    dc = {"status": DIFFICULT_CASE_STATUS,
          "note": "Base rule 25OB10.0(4) and condonation 25OB10.0(5) found in the supplied PDF; examination bye-laws "
                  "NOT VERIFIED. The agent pipeline exists, but the case is NOT claimed to pass: no real LLM run and open interpretation "
                  "questions (see docs/corpus_verification.md).",
          "verified_passages_indexed": False}
    warnings: list[str] = []
    errors: list[str] = []
    vp: dict[str, bool] = {}
    docs = chunks = 0
    tag = None
    if last_ok:
        m = last_ok["manifest"]
        docs, chunks, tag = len(m.get("documents", [])), m.get("chunks_total", 0), m.get("embedding_tag")
        warnings = m.get("warnings", [])
        vp = m.get("verified_passages", {})
        dc["verified_passages_indexed"] = bool(vp) and all(vp.values())
    if last_any and last_any["status"] != "success":
        errors = last_any["manifest"].get("errors", []) or ["last ingestion failed"]
    index_exists = bool(last_ok) and chunks > 0
    ready = index_exists and reachable and (last_any is None or last_any["status"] == "success")
    if not sources:
        msg = "No source PDFs found in the corpus directory."
    elif not last_any:
        msg = "Ingestion has not run yet. Run: docker compose run --rm ingest"
    elif not ready:
        msg = "Corpus is NOT ready: " + ("; ".join(errors) if errors else "index unavailable or Chroma unreachable")
    else:
        msg = "Corpus indexed and Chroma reachable."
    return CorpusStatus(
        ready=ready, sources_present=sources, index_exists=index_exists, chroma_reachable=reachable,
        parse_ok=(last_any["status"] == "success") if last_any else None,
        documents_indexed=docs, chunks_indexed=chunks, embedding_tag=tag,
        last_ingest_at=last_ok["finished_at"] if last_ok else None,
        last_attempt_status=last_any["status"] if last_any else None,
        last_attempt_at=last_any["finished_at"] if last_any else None,
        warnings=warnings, errors=errors, verified_passages=vp, difficult_case=dc, message=msg)


configure_logging("api")
setup_tracing("triage-api")
app = create_app()
