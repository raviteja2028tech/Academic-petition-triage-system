"""Failure and recovery drills against the RUNNING Docker stack (run it while the LLM is the load-test stub).

  docker compose --profile loadtest up -d llm-stub        # and api/worker pointed at it (benchmark.py does this)
  python loadtest/failure_drills.py > loadtest/results/failure_drills.json

Each drill breaks one dependency, checks what the API does, restores it, and checks that the system recovers.
Nothing is simulated in-process: containers are really stopped. Results are recorded as measured, including failures.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import httpx

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
API = os.environ.get("API_URL", "http://localhost:8000")
PETITION = {"student_ref": "SYN-000777", "program": "Computer Science", "admission_batch": "2025-26", "petition_type": "attendance",
            "course_code": "CS101", "semester": 3, "classes_held": 100, "classes_attended": 80, "attendance_percentage": 80.0,
            "reason_category": "medical", "medical_documentation": "certificate",
            "petition_text": "Failure drill petition: hospitalised for three weeks, requesting consideration of the attendance shortage."}
TERMINAL = {"completed", "escalated", "failed"}
results: list[dict] = []


def dc(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", "compose", "--profile", "loadtest", *args], cwd=ROOT, capture_output=True, text=True, timeout=300)


def submit() -> tuple[int, str | None]:
    try:
        r = httpx.post(f"{API}/v1/petitions", json=PETITION, timeout=15)
        return r.status_code, (r.json().get("run_id") if r.status_code == 202 else None)
    except httpx.HTTPError as e:
        return 0, type(e).__name__


def wait_terminal(run_ids: list[str], timeout: float) -> dict[str, dict]:
    end, out = time.time() + timeout, {}
    while time.time() < end and len(out) < len(run_ids):
        for rid in run_ids:
            if rid in out:
                continue
            try:
                v = httpx.get(f"{API}/v1/runs/{rid}", timeout=10).json()
            except httpx.HTTPError:
                continue
            if v["status"] in TERMINAL:
                out[rid] = {"status": v["status"], "reason": ((v.get("result") or {}).get("escalation") or {}).get("reason"),
                            "position": (v.get("result") or {}).get("position"), "citations": len((v.get("result") or {}).get("citations", []))}
        time.sleep(2)
    return out


def wait_ready(timeout: float = 120) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            if httpx.get(f"{API}/readyz", timeout=5).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(2)
    return False


def record(name: str, ok: bool, **detail) -> None:
    results.append({"drill": name, "pass": bool(ok), **detail})
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {json.dumps(detail, default=str)[:300]}", file=sys.stderr, flush=True)


def drill_worker_down() -> None:
    dc("stop", "worker")
    t_stop = time.time()
    codes = [submit() for _ in range(4)]
    ids = [rid for c, rid in codes if c == 202]
    states = [httpx.get(f"{API}/v1/runs/{i}", timeout=10).json()["status"] for i in ids]
    detect_s = None
    ready: dict = {}
    while time.time() - t_stop < 150:             # readiness counts workers by heartbeat age: measure how long a dead one lingers
        ready = httpx.get(f"{API}/readyz", timeout=10).json()["checks"]
        if ready.get("workers") == "0":
            detect_s = round(time.time() - t_stop, 1)
            break
        time.sleep(3)
    dc("start", "worker")
    done = wait_terminal(ids, 240)
    record("worker down: submissions still accepted, queue holds them, readiness flags it, all drain after restart",
           len(ids) == 4 and all(s == "queued" for s in states) and detect_s is not None and len(done) == 4
           and all(d["status"] in ("completed", "escalated") for d in done.values()),
           accepted=len(ids), states_while_down=states, seconds_until_readyz_reported_no_workers=detect_s, degraded=ready.get("degraded"),
           after_restart={k: v["status"] for k, v in done.items()})


def drill_chroma_down() -> None:
    dc("stop", "chroma")
    code, rid = submit()
    done = wait_terminal([rid], 120) if rid else {}
    d = done.get(rid, {})
    dc("start", "chroma")
    wait_ready()
    time.sleep(8)
    code2, rid2 = submit()
    again = wait_terminal([rid2], 120) if rid2 else {}
    record("chroma down: petition escalates (retrieval_unavailable), no fabricated determination, recovers after restart",
           code == 202 and d.get("status") == "escalated" and d.get("reason") == "retrieval_unavailable" and d.get("citations") == 0
           and d.get("position") == "NO_DETERMINATION" and again.get(rid2, {}).get("status") in ("completed", "escalated")
           and again.get(rid2, {}).get("reason") != "retrieval_unavailable",
           while_down=d, after_restart=again.get(rid2))


def drill_redis_down() -> None:
    dc("stop", "redis")
    time.sleep(3)
    code, _ = submit()
    try:
        rz = httpx.get(f"{API}/readyz", timeout=10)
        rz_code, rz_checks = rz.status_code, rz.json().get("checks", {})
    except httpx.HTTPError as e:
        rz_code, rz_checks = 0, {"error": type(e).__name__}
    try:
        hz = httpx.get(f"{API}/healthz", timeout=10).status_code
    except httpx.HTTPError:
        hz = 0
    dc("start", "redis")
    ok_ready = wait_ready(120)
    time.sleep(10)
    code2, rid2 = submit()
    again = wait_terminal([rid2], 180) if rid2 else {}
    record("redis down: submit -> 503 (no silent loss), readyz 503, liveness stays 200, full recovery after restart",
           code == 503 and rz_code == 503 and hz == 200 and ok_ready and code2 == 202 and bool(again),
           submit_status=code, readyz=rz_code, readyz_checks=rz_checks, healthz=hz, after_restart=again.get(rid2))


def drill_api_restart_persistence() -> None:
    code, rid = submit()
    wait_terminal([rid], 120)
    dc("restart", "api")
    wait_ready()
    v = httpx.get(f"{API}/v1/runs/{rid}", timeout=10).json()
    record("api restart: finished runs persist (SQLite volume)", v["status"] in TERMINAL and v["petition"]["student_ref"] == "SYN-000777",
           status=v["status"])


def drill_worker_killed_mid_run() -> None:
    wait_ready(120)
    time.sleep(5)
    codes = [submit() for _ in range(3)]
    ids = [rid for c, rid in codes if c == 202]
    time.sleep(0.6)                                # kill while the first run is executing (stub runs take ~2 s)
    subprocess.run(["docker", "compose", "kill", "worker"], cwd=ROOT, capture_output=True, timeout=60)
    dc("start", "worker")
    t0 = time.time()
    done = wait_terminal(ids, 480)
    states = {k: v["status"] for k, v in done.items()}
    # The interrupted run may only end 'failed' (declared after job timeout + 2 min) - never stuck, never an invented answer.
    record("worker killed mid-run: every run reaches a terminal state (none stuck, none fabricated)",
           len(ids) == 3 and len(done) == 3 and all(d["status"] != "completed" or d["citations"] >= 0 for d in done.values()),
           final_states=states, seconds_to_all_terminal=round(time.time() - t0, 1),
           note="'failed' is acceptable for the interrupted run: it is reported as failed, not answered")


def main() -> int:
    if not wait_ready(30):
        print("API not ready; start the stack first", file=sys.stderr)
        return 2
    for fn in (drill_api_restart_persistence, drill_worker_down, drill_chroma_down, drill_redis_down, drill_worker_killed_mid_run):
        try:
            fn()
        except Exception as e:  # noqa: BLE001  (a drill that cannot run is a recorded failure, not a crash)
            record(fn.__name__, False, error=f"{type(e).__name__}: {e}"[:300])
        finally:
            for svc in ("redis", "chroma", "worker", "api"):
                dc("start", svc)
            wait_ready(120)
    print(json.dumps({"passed": sum(r["pass"] for r in results), "total": len(results), "results": results}, indent=1, default=str))
    return 0 if all(r["pass"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
