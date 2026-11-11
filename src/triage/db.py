"""SQLite persistence (WAL). One short-lived connection per operation; shared by api, worker and ingest."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  client_id TEXT,
  correlation_id TEXT,
  mode TEXT NOT NULL DEFAULT 'placeholder',
  petition_json TEXT NOT NULL,
  result_json TEXT,
  error TEXT
);
CREATE TABLE IF NOT EXISTS run_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  event TEXT NOT NULL,
  detail_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_run ON run_events(run_id);
CREATE TABLE IF NOT EXISTS quarantine (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  client_id TEXT,
  payload_hash TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  errors_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  client_id TEXT NOT NULL,
  rating INTEGER NOT NULL,
  agrees INTEGER,
  comment TEXT,
  UNIQUE(run_id, client_id)
);
CREATE TABLE IF NOT EXISTS run_evals (
  run_id TEXT PRIMARY KEY,
  ts TEXT NOT NULL,
  status TEXT NOT NULL,
  scores_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS examiner_decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  examiner_label TEXT NOT NULL,
  decision TEXT NOT NULL,
  note TEXT NOT NULL,
  ai_snapshot_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_exdec_run ON examiner_decisions(run_id);
CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  filename TEXT NOT NULL,
  content_type TEXT NOT NULL,
  size INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  path TEXT NOT NULL,
  UNIQUE(run_id, sha256)
);
CREATE TABLE IF NOT EXISTS ingest_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT NOT NULL,
  finished_at TEXT NOT NULL,
  status TEXT NOT NULL,
  manifest_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
  user_id TEXT PRIMARY KEY,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL,
  name TEXT NOT NULL,
  email TEXT,
  branch TEXT,
  semester INTEGER,
  section TEXT,
  usn TEXT,
  created_at TEXT NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS auth_sessions (
  token TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  role TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  revoked INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON auth_sessions(user_id);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def new_run_id() -> str:
    return "run_" + uuid.uuid4().hex[:16]


@contextmanager
def connect(db_path: str) -> Iterator[sqlite3.Connection]:
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(SCHEMA)
        try:
            cursor = conn.execute("PRAGMA table_info(users)")
            cols = {row["name"] for row in cursor.fetchall()}
            for col, col_type in (("branch", "TEXT"), ("semester", "INTEGER"), ("section", "TEXT"), ("usn", "TEXT")):
                if col not in cols:
                    conn.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
        except Exception:
            pass
        yield conn
    finally:
        conn.close()


def check(db_path: str) -> None:
    with connect(db_path) as c:
        c.execute("SELECT 1 FROM runs LIMIT 1")


# ---------- runs ----------
def create_run(db_path: str, petition: dict, client_id: Optional[str], correlation_id: str) -> str:
    run_id = new_run_id()
    ts = now()
    with connect(db_path) as c:
        c.execute("BEGIN IMMEDIATE")
        c.execute(
            "INSERT INTO runs(run_id,status,created_at,updated_at,client_id,correlation_id,petition_json) VALUES(?,?,?,?,?,?,?)",
            (run_id, "queued", ts, ts, client_id, correlation_id, json.dumps(petition)),
        )
        c.execute("INSERT INTO run_events(run_id,ts,event,detail_json) VALUES(?,?,?,?)",
                  (run_id, ts, "queued", json.dumps({"correlation_id": correlation_id})))
        c.execute("COMMIT")
    return run_id


def set_status(db_path: str, run_id: str, status: str, result: Optional[dict] = None,
               error: Optional[str] = None, detail: Optional[dict] = None) -> None:
    ts = now()
    with connect(db_path) as c:
        c.execute("BEGIN IMMEDIATE")
        c.execute(
            "UPDATE runs SET status=?, updated_at=?, result_json=COALESCE(?,result_json), error=COALESCE(?,error) WHERE run_id=?",
            (status, ts, json.dumps(result) if result is not None else None, error, run_id),
        )
        c.execute("INSERT INTO run_events(run_id,ts,event,detail_json) VALUES(?,?,?,?)",
                  (run_id, ts, status, json.dumps(detail or {})))
        c.execute("COMMIT")


def add_event(db_path: str, run_id: str, event: str, detail: Optional[dict] = None) -> None:
    with connect(db_path) as c:
        c.execute("INSERT INTO run_events(run_id,ts,event,detail_json) VALUES(?,?,?,?)",
                  (run_id, now(), event, json.dumps(detail or {}, default=str)))


def set_mode(db_path: str, run_id: str, mode: str) -> None:
    with connect(db_path) as c:
        c.execute("UPDATE runs SET mode=? WHERE run_id=?", (mode, run_id))


def get_run(db_path: str, run_id: str) -> Optional[dict[str, Any]]:
    with connect(db_path) as c:
        r = c.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if not r:
            return None
        ev = c.execute("SELECT ts,event,detail_json FROM run_events WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
    out = dict(r)
    out["petition"] = json.loads(out.pop("petition_json"))
    rj = out.pop("result_json", None)
    out["result"] = json.loads(rj) if rj else None
    out["events"] = [{"ts": e["ts"], "event": e["event"], "detail": json.loads(e["detail_json"])} for e in ev]
    return out


def fail_if_stale(db_path: str, run_id: str, max_age_seconds: float) -> bool:
    """A run stuck in 'running' longer than the worker job timeout means the worker died or was killed (RQ kills
    timed-out jobs without running our code). Mark it failed so clients are not left polling forever."""
    with connect(db_path) as c:
        r = c.execute("SELECT status, updated_at FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if not r or r["status"] != "running":
        return False
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(r["updated_at"])).total_seconds()
    if age <= max_age_seconds:
        return False
    set_status(db_path, run_id, "failed",
               error=f"worker stopped responding (no progress for {int(age)}s; job timeout or worker crash)",
               detail={"reason": "stale_running", "age_seconds": int(age)})
    return True


def list_runs(db_path: str, limit: int = 20, status: Optional[str] = None, student_ref: Optional[str] = None,
              petition_type: Optional[str] = None, offset: int = 0, real_only: bool = False,
              awaiting_decision: Optional[bool] = None) -> tuple[dict[str, int], list[dict], int]:
    """Returns (status counts, page of runs, number of runs matching ALL filters). real_only drops runs answered by a
    stub/scripted model or by no model; awaiting_decision=True keeps finished runs with no human decision, False keeps decided ones."""
    where, args = [], []
    json_filtered = bool(student_ref or petition_type or real_only or awaiting_decision is not None)
    if status:
        where.append("status=?")
        args.append(status)
    with connect(db_path) as c:
        counts = {r["status"]: r["n"] for r in c.execute("SELECT status, COUNT(*) n FROM runs GROUP BY status")}
        sql = "SELECT run_id,status,created_at,updated_at,petition_json,result_json FROM runs"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC"
        # student_ref / petition_type live inside the JSON, so they are filtered after the (bounded) fetch
        rows = c.execute(sql + (" LIMIT ? OFFSET ?" if not json_filtered else " LIMIT 5000"),
                         args + ([limit, offset] if not json_filtered else [])).fetchall()
        decided = {r["run_id"] for r in c.execute("SELECT DISTINCT run_id FROM examiner_decisions")} if awaiting_decision is not None else set()
    out = []
    for r in rows:
        p = json.loads(r["petition_json"])
        if awaiting_decision is not None:
            finished = r["status"] in ("completed", "escalated", "failed")
            if awaiting_decision and not (finished and r["run_id"] not in decided):
                continue
            if awaiting_decision is False and r["run_id"] not in decided:
                continue
        if real_only:
            res0 = json.loads(r["result_json"]) if r["result_json"] else None
            if not (res0 and res0.get("llm_models") and not _is_stub(res0)):
                continue
        if student_ref and p.get("student_ref") != student_ref:
            continue
        if petition_type and p.get("petition_type") != petition_type:
            continue
        res = json.loads(r["result_json"]) if r["result_json"] else {}
        out.append({"run_id": r["run_id"], "status": r["status"], "created_at": r["created_at"],
                    "updated_at": r["updated_at"], "petition_type": p.get("petition_type"),
                    "student_ref": p.get("student_ref"), "course_code": p.get("course_code"),
                    "attendance_percentage": p.get("attendance_percentage"),
                    "route": res.get("route"), "escalation_reason": (res.get("escalation") or {}).get("reason"),
                    "llm_models": res.get("llm_models") or []})
    matched = len(out) if json_filtered else counts.get(status, 0) if status else sum(counts.values())
    if json_filtered:
        out = out[offset:offset + limit]
    return counts, out, matched


def count_runs(db_path: str) -> int:
    with connect(db_path) as c:
        return c.execute("SELECT COUNT(*) FROM runs").fetchone()[0]


# ---------- quarantine ----------
def quarantine(db_path: str, raw: Any, errors: list[dict], client_id: Optional[str]) -> int:
    payload = raw if isinstance(raw, str) else json.dumps(raw, sort_keys=True, default=str)
    h = hashlib.sha256(payload.encode("utf-8", "replace")).hexdigest()
    with connect(db_path) as c:
        cur = c.execute(
            "INSERT INTO quarantine(ts,client_id,payload_hash,payload_json,errors_json) VALUES(?,?,?,?,?)",
            (now(), client_id, h, payload[:20000], json.dumps(errors)),
        )
        return cur.lastrowid


def list_quarantine(db_path: str, limit: int = 50) -> list[dict]:
    with connect(db_path) as c:
        rows = c.execute("SELECT * FROM quarantine ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [{**dict(r), "errors": json.loads(r["errors_json"])} for r in rows]


def count_quarantine(db_path: str) -> int:
    with connect(db_path) as c:
        return c.execute("SELECT COUNT(*) FROM quarantine").fetchone()[0]


# ---------- ingestion manifests ----------
def save_ingest(db_path: str, started_at: str, status: str, manifest: dict) -> None:
    with connect(db_path) as c:
        c.execute("INSERT INTO ingest_runs(started_at,finished_at,status,manifest_json) VALUES(?,?,?,?)",
                  (started_at, now(), status, json.dumps(manifest)))


def last_ingest(db_path: str, only_success: bool = False) -> Optional[dict]:
    q = "SELECT * FROM ingest_runs " + ("WHERE status='success' " if only_success else "") + "ORDER BY id DESC LIMIT 1"
    with connect(db_path) as c:
        r = c.execute(q).fetchone()
    if not r:
        return None
    return {"status": r["status"], "started_at": r["started_at"], "finished_at": r["finished_at"],
            "manifest": json.loads(r["manifest_json"])}


# ---------- feedback / evaluation / statistics ----------
def upsert_feedback(db_path: str, run_id: str, client_id: str, rating: int, agrees: Optional[bool],
                    comment: Optional[str]) -> None:
    with connect(db_path) as c:
        c.execute("INSERT INTO feedback(run_id,ts,client_id,rating,agrees,comment) VALUES(?,?,?,?,?,?) "
                  "ON CONFLICT(run_id,client_id) DO UPDATE SET ts=excluded.ts, rating=excluded.rating, "
                  "agrees=excluded.agrees, comment=excluded.comment",
                  (run_id, now(), client_id, rating, None if agrees is None else int(agrees), comment))


def feedback_stats(db_path: str) -> dict:
    with connect(db_path) as c:
        rows = c.execute("SELECT rating, agrees FROM feedback").fetchall()
    n = len(rows)
    dist = {str(i): sum(1 for r in rows if r["rating"] == i) for i in range(1, 6)}
    ag = [r["agrees"] for r in rows if r["agrees"] is not None]
    return {"count": n, "mean_rating": round(sum(r["rating"] for r in rows) / n, 3) if n else None,
            "satisfaction_rate": round(sum(1 for r in rows if r["rating"] >= 4) / n, 3) if n else None,
            "distribution": dist, "agreement_rate": round(sum(ag) / len(ag), 3) if ag else None,
            "agreement_count": len(ag)}


def list_feedback(db_path: str, limit: int = 50) -> list[dict]:
    with connect(db_path) as c:
        rows = c.execute("SELECT run_id,ts,rating,agrees,comment FROM feedback ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def save_eval(db_path: str, run_id: str, status: str, scores: dict) -> None:
    with connect(db_path) as c:
        c.execute("INSERT OR REPLACE INTO run_evals(run_id,ts,status,scores_json) VALUES(?,?,?,?)",
                  (run_id, now(), status, json.dumps(scores)))


STUB_WORDS = ("stub", "scripted", "fake", "mock")


def _is_stub(res: Optional[dict]) -> bool:
    return any(w in m.lower() for m in (res or {}).get("llm_models", []) for w in STUB_WORDS)


def run_stats(db_path: str, limit: int = 1000, real_only: bool = False) -> dict:
    """Aggregates over the most recent runs: outcomes, escalation reasons, latency, tokens, cost."""
    with connect(db_path) as c:
        rows = c.execute("SELECT status, created_at, updated_at, result_json, petition_json FROM runs "
                         "ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        if real_only:        # drop runs answered by a stub/scripted model (load tests, demos) and runs where no model answered
            rows = [r for r in rows if r["result_json"] and (lambda x: x.get("llm_models") and not _is_stub(x))(json.loads(r["result_json"]))]
        ev = [json.loads(r["scores_json"]) for r in c.execute("SELECT scores_json FROM run_evals WHERE status='ok'")]
    by_status: dict[str, int] = {}
    reasons: dict[str, int] = {}
    lat: list[float] = []
    ptok = ctok = n_cost = unknown_cost = est_runs = 0
    usd = 0.0
    by_type: dict[str, int] = {}
    by_day: dict[str, dict] = {}
    by_model: dict[str, int] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        pt = json.loads(r["petition_json"]).get("petition_type", "unknown")
        by_type[pt] = by_type.get(pt, 0) + 1
        day = by_day.setdefault(r["created_at"][:10], {"total": 0, "escalated": 0})
        day["total"] += 1
        day["escalated"] += r["status"] == "escalated"
        for m in (json.loads(r["result_json"]).get("llm_models") or []) if r["result_json"] else []:
            by_model[m] = by_model.get(m, 0) + 1
        if r["status"] in ("completed", "escalated", "failed"):
            lat.append((datetime.fromisoformat(r["updated_at"]) - datetime.fromisoformat(r["created_at"])).total_seconds())
        res = json.loads(r["result_json"]) if r["result_json"] else None
        if not res or res.get("mode") != "agents":
            continue
        esc = res.get("escalation") or {}
        if esc.get("required"):
            k = esc.get("reason") or "unknown"
            reasons[k] = reasons.get(k, 0) + 1
        cst = res.get("cost")
        if cst and cst.get("llm_calls"):
            ptok += cst["prompt_tokens"]
            ctok += cst["completion_tokens"]
            est_runs += cst["token_source"] != "reported"
            if cst["estimated_cost_usd"] is None:
                unknown_cost += 1
            else:
                n_cost += 1
                usd += cst["estimated_cost_usd"]
    lat.sort()

    def pct(p: float):
        return round(lat[min(len(lat) - 1, int(p * len(lat)))], 3) if lat else None

    avg = usd / n_cost if n_cost else None
    judged = {}
    for k in ("context_relevance", "groundedness", "faithfulness"):
        vals = [e[k] for e in ev if k in e]
        if vals:
            judged[k] = round(sum(vals) / len(vals), 3)
    return {"runs_considered": len(rows), "real_only": real_only, "by_status": by_status,
            "by_type": by_type, "by_day": dict(sorted(by_day.items())), "by_model": by_model, "escalation_reasons": reasons,
            "latency_seconds": {"p50": pct(0.5), "p95": pct(0.95), "n": len(lat)},
            "tokens": {"prompt": ptok, "completion": ctok, "runs_with_estimated_tokens": est_runs},
            "cost": {"runs_with_known_cost": n_cost, "runs_with_unknown_cost": unknown_cost,
                     "total_usd": round(usd, 6) if n_cost else None,
                     "avg_usd_per_run": round(avg, 6) if avg is not None else None,
                     "usd_per_100_runs": round(avg * 100, 4) if avg is not None else None,
                     "note": "Estimate. Unknown when no price is configured (PRICE_PROMPT_PER_1K / PRICE_COMPLETION_PER_1K)."},
            "auto_eval": {"runs_scored": len(ev), **judged}}


# ---------- human examiner decisions (recorded SEPARATELY from the AI recommendation, append-only) ----------
def add_examiner_decision(db_path: str, run_id: str, examiner_label: str, decision: str, note: str,
                          ai_snapshot: dict) -> int:
    with connect(db_path) as c:
        cur = c.execute("INSERT INTO examiner_decisions(run_id,ts,examiner_label,decision,note,ai_snapshot_json) "
                        "VALUES(?,?,?,?,?,?)", (run_id, now(), examiner_label, decision, note, json.dumps(ai_snapshot)))
        return int(cur.lastrowid)


def list_examiner_decisions(db_path: str, run_id: str) -> list[dict]:
    with connect(db_path) as c:
        rows = c.execute("SELECT id,ts,examiner_label,decision,note,ai_snapshot_json FROM examiner_decisions "
                         "WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
    return [{"id": r["id"], "ts": r["ts"], "examiner_label": r["examiner_label"], "decision": r["decision"],
             "note": r["note"], "ai_snapshot": json.loads(r["ai_snapshot_json"])} for r in rows]


def latest_decisions(db_path: str, run_ids: list[str]) -> dict[str, dict]:
    if not run_ids:
        return {}
    q = ",".join("?" * len(run_ids))
    with connect(db_path) as c:
        rows = c.execute(f"SELECT run_id,decision,ts FROM examiner_decisions WHERE id IN "
                         f"(SELECT MAX(id) FROM examiner_decisions WHERE run_id IN ({q}) GROUP BY run_id)", run_ids).fetchall()
    return {r["run_id"]: {"decision": r["decision"], "ts": r["ts"]} for r in rows}


# ---------- supporting documents (stored, never parsed or sent to a model) ----------
def add_document(db_path: str, run_id: str, filename: str, content_type: str, size: int, sha256: str,
                 path: str) -> Optional[int]:
    with connect(db_path) as c:
        cur = c.execute("INSERT OR IGNORE INTO documents(run_id,ts,filename,content_type,size,sha256,path) "
                        "VALUES(?,?,?,?,?,?,?)", (run_id, now(), filename, content_type, size, sha256, path))
        return int(cur.lastrowid) if cur.rowcount else None


def list_documents(db_path: str, run_id: str) -> list[dict]:
    with connect(db_path) as c:
        rows = c.execute("SELECT id,ts,filename,content_type,size,sha256 FROM documents WHERE run_id=? ORDER BY id",
                         (run_id,)).fetchall()
    return [dict(r) for r in rows]


def get_document(db_path: str, run_id: str, doc_id: int) -> Optional[dict]:
    with connect(db_path) as c:
        r = c.execute("SELECT * FROM documents WHERE run_id=? AND id=?", (run_id, doc_id)).fetchone()
    return dict(r) if r else None


def agent_stats(db_path: str, limit: int = 500, real_only: bool = False) -> dict:
    """Per-agent executions, failures and mean seconds, derived from persisted run_events of the latest runs."""
    with connect(db_path) as c:
        ids = [r["run_id"] for r in c.execute("SELECT run_id, result_json FROM runs ORDER BY created_at DESC LIMIT ?", (limit,))
               if not real_only or (r["result_json"] and (lambda x: x.get("llm_models") and not _is_stub(x))(json.loads(r["result_json"])))]
        if not ids:
            return {"runs_considered": 0, "agents": {}}
        q = ",".join("?" * len(ids))
        ev = c.execute(f"SELECT run_id, ts, event, detail_json FROM run_events WHERE run_id IN ({q}) "
                       f"AND event IN ('agent_start','agent_end') ORDER BY id", ids).fetchall()
    starts: dict[tuple, str] = {}
    agents: dict[str, dict] = {}
    for e in ev:
        d = json.loads(e["detail_json"])
        a = d.get("agent", "?")
        if e["event"] == "agent_start":
            starts[(e["run_id"], a)] = e["ts"]
            continue
        row = agents.setdefault(a, {"executions": 0, "failures": 0, "seconds": []})
        row["executions"] += 1
        row["failures"] += 0 if d.get("ok") else 1
        t0 = starts.pop((e["run_id"], a), None)
        if t0:
            row["seconds"].append((datetime.fromisoformat(e["ts"]) - datetime.fromisoformat(t0)).total_seconds())
    for row in agents.values():
        sec = sorted(row.pop("seconds"))
        row["mean_seconds"] = round(sum(sec) / len(sec), 3) if sec else None
        row["p95_seconds"] = round(sec[min(len(sec) - 1, int(0.95 * len(sec)))], 3) if sec else None
    return {"runs_considered": len(ids), "agents": agents}


# ---------- authentication & sessions ----------
def upsert_user(db_path: str, user_id: str, password_hash: str, role: str, name: str,
                email: Optional[str] = None, branch: Optional[str] = None,
                semester: Optional[int] = None, section: Optional[str] = None,
                usn: Optional[str] = None, is_active: int = 1) -> None:
    ts = now()
    with connect(db_path) as c:
        c.execute(
            """INSERT INTO users(user_id, password_hash, role, name, email, branch, semester, section, usn, created_at, is_active)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 password_hash=excluded.password_hash,
                 role=excluded.role,
                 name=excluded.name,
                 email=excluded.email,
                 branch=excluded.branch,
                 semester=excluded.semester,
                 section=excluded.section,
                 usn=excluded.usn,
                 is_active=excluded.is_active""",
            (user_id, password_hash, role, name, email, branch, semester, section, usn, ts, is_active)
        )


def get_user(db_path: str, user_id: str) -> Optional[dict]:
    with connect(db_path) as c:
        r = c.execute("SELECT user_id, password_hash, role, name, email, branch, semester, section, usn, created_at, is_active FROM users WHERE user_id=?",
                      (user_id,)).fetchone()
    return dict(r) if r else None


def list_users(db_path: str, role: Optional[str] = None) -> list[dict]:
    with connect(db_path) as c:
        if role:
            rows = c.execute("SELECT user_id, role, name, email, branch, semester, section, usn, created_at, is_active FROM users WHERE role=? ORDER BY user_id",
                             (role,)).fetchall()
        else:
            rows = c.execute("SELECT user_id, role, name, email, branch, semester, section, usn, created_at, is_active FROM users ORDER BY user_id").fetchall()
    return [dict(r) for r in rows]


def create_auth_session(db_path: str, token: str, user_id: str, role: str, expires_at: str) -> None:
    ts = now()
    with connect(db_path) as c:
        c.execute("INSERT INTO auth_sessions(token, user_id, role, created_at, expires_at, revoked) VALUES(?,?,?,?,?,0)",
                  (token, user_id, role, ts, expires_at))


def get_auth_session(db_path: str, token: str) -> Optional[dict]:
    with connect(db_path) as c:
        r = c.execute(
            """SELECT s.token, s.user_id, s.role, s.created_at, s.expires_at, s.revoked,
                      u.name, u.email, u.branch, u.semester, u.section, u.usn, u.is_active
               FROM auth_sessions s
               JOIN users u ON s.user_id = u.user_id
               WHERE s.token = ? AND s.revoked = 0 AND s.expires_at > ? AND u.is_active = 1""",
            (token, now())
        ).fetchone()
    return dict(r) if r else None


def revoke_auth_session(db_path: str, token: str) -> bool:
    with connect(db_path) as c:
        cur = c.execute("UPDATE auth_sessions SET revoked=1 WHERE token=?", (token,))
        return cur.rowcount > 0


def revoke_user_sessions(db_path: str, user_id: str) -> int:
    with connect(db_path) as c:
        cur = c.execute("UPDATE auth_sessions SET revoked=1 WHERE user_id=?", (user_id,))
        return cur.rowcount


def cleanup_expired_sessions(db_path: str) -> int:
    with connect(db_path) as c:
        cur = c.execute("DELETE FROM auth_sessions WHERE expires_at <= ? OR revoked=1", (now(),))
        return cur.rowcount

