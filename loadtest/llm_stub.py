"""OpenAI-compatible LLM STUB for load testing and Docker integration. It replaces ONLY the LLM: the API, queue,
workers, embeddings, Chroma and retrieval stay real.

It is stateless and deterministic: the reply depends only on the request text (agent role inferred from the system
prompt; research progress inferred from the "Previous tool calls" history in the user prompt; verifier citations built
from the evidence passed to it). So it drives the real pipeline down the assignment's attendance-condonation path and
produces verified citations - which exercises the system, and proves NOTHING about any real model's quality.

Environment (all optional):
  STUB_LATENCY_MS=300        mean latency per call;  STUB_LATENCY_JITTER=0.3  (+-30 % uniform)
  STUB_ERROR_RATE=0.0        fraction answered with HTTP 500
  STUB_RATE_LIMIT_RATE=0.0   fraction answered with HTTP 429 + Retry-After: 1
  STUB_TIMEOUT_RATE=0.0      fraction that hang for STUB_TIMEOUT_SECONDS (default 60) to trigger client timeouts
  STUB_SEED=1                seed for the failure/latency random generator
Run:  uvicorn loadtest.llm_stub:app --port 9100        (POST /v1/chat/completions, GET /healthz, GET /stats)
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import re
import threading

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="LLM stub (load test)")
_rng = random.Random(int(os.environ.get("STUB_SEED", "1")))
_lock = threading.Lock()
_stats = {"requests": 0, "ok": 0, "http_500": 0, "http_429": 0, "hung": 0}

BASE_QUOTE = "minimum attendance of 85 % in each registered course"
COND_QUOTE = "a shortage up to a maximum of 10 % may be condoned by the Vice-Chancellor"
# Scripted ambiguity rule: the stub treats petition text with none of these words as unclear. This demonstrates the pipeline's handling of a
# low-confidence triage result; it is not language understanding.
VAGUE_KEYWORDS = ("attendance", "class", "absent", "hospital", "medical", "ill", "sick", "fever", "accident", "missed", "condon",
                  "shortage", "bereavement", "sports", "emergency", "surgery", "treatment")

RESEARCH = [
    {"tool": "search_keyword", "args": {"query": "minimum attendance required in each registered course", "k": 5}, "reason": "base rule"},
    {"tool": "search_semantic", "args": {"query": "attendance shortage condoned medical reasons Vice-Chancellor", "k": 5}, "reason": "modifying provision"},
    {"tool": "finish", "args": {}, "reason": "evidence sufficient"},
]


def _f(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _eid(user: str, clause: str) -> str | None:
    m = re.search(r"\[(E\d+)\][^\n]*clause " + re.escape(clause) + r" \|", user)
    return m.group(1) if m else None


def _reply(system: str, user: str) -> dict:
    s = system.lower()
    if "triage agent" in s:
        text = ""
        try:
            text = json.loads(user[user.index("{"):user.rindex("}") + 1]).get("petition_text", "")
        except Exception:  # noqa: BLE001
            pass
        vague = not any(w in text.lower() for w in VAGUE_KEYWORDS)      # scripted rule, NOT real understanding
        return {"classified_type": "attendance", "confidence": 0.3 if vague else 0.9, "attendance_percentage_in_text": None,
                "medical_grounds_claimed": not vague, "summary": "request is unclear" if vague else "requests consideration of an attendance shortage",
                "flags": ["petition text does not say what is being requested"] if vague else []}
    if "research agent" in s:
        m = re.search(r"Previous tool calls this run:\s*(\[.*?\])\s*\n\s*\nRemaining", user, re.S)
        done = len(json.loads(m.group(1))) if m else 0
        return RESEARCH[min(done, len(RESEARCH) - 1)]
    if "verifier" in s:
        cites = []
        for clause, quote in (("25OB10.0(4)", BASE_QUOTE), ("25OB10.0(5)", COND_QUOTE)):
            e = _eid(user, clause)
            if e:
                cites.append({"evidence_id": e, "clause_id": clause, "quote": quote})
        return {"route": "refer-to-committee",
                "position": "Attendance is below the 85 % minimum; a shortage may be condoned only by the Vice-Chancellor.",
                "basis": "The base rule sets the minimum; the condonation provision reserves the decision to an authority.",
                "citations": cites,
                "escalation": {"required": True, "reason": "committee_discretion",
                               "detail": "Condonation is decided by the Vice-Chancellor on recommendation; a human decides."}}
    if "judge" in s:
        return {"context_relevance": 0.8, "groundedness": 1.0, "faithfulness": 1.0, "rationale": "stub"}
    return {"error": "unrecognised role"}


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/stats")
def stats():
    return _stats


@app.post("/v1/chat/completions")
async def chat(request: Request):
    body = await request.json()
    msgs = body.get("messages", [])
    system = next((m["content"] for m in msgs if m["role"] == "system"), "")
    user = next((m["content"] for m in reversed(msgs) if m["role"] == "user"), "")
    with _lock:
        _stats["requests"] += 1
        roll, jit = _rng.random(), _rng.uniform(-1, 1)
    err, rl, to = _f("STUB_ERROR_RATE", 0), _f("STUB_RATE_LIMIT_RATE", 0), _f("STUB_TIMEOUT_RATE", 0)
    if roll < to:
        with _lock:
            _stats["hung"] += 1
        await asyncio.sleep(_f("STUB_TIMEOUT_SECONDS", 60))
    elif roll < to + err:
        with _lock:
            _stats["http_500"] += 1
        return JSONResponse({"error": {"message": "stub: injected server error"}}, status_code=500)
    elif roll < to + err + rl:
        with _lock:
            _stats["http_429"] += 1
        return JSONResponse({"error": {"message": "stub: injected rate limit"}}, status_code=429, headers={"Retry-After": "1"})
    await asyncio.sleep(max(0.0, _f("STUB_LATENCY_MS", 300) / 1000.0 * (1 + _f("STUB_LATENCY_JITTER", 0.3) * jit)))
    text = json.dumps(_reply(system, user))
    with _lock:
        _stats["ok"] += 1
    return {"id": "stub", "object": "chat.completion", "model": "stub-model",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": max(1, (len(system) + len(user)) // 4), "completion_tokens": max(1, len(text) // 4),
                      "total_tokens": 0}}
