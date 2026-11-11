"""Structured JSON logging with correlation ids and secret redaction.

Every record carries service, level, logger, message, correlation_id and run_id (context variables set by the API
middleware and the worker). Redaction is applied to the final rendered line: bearer tokens, `sk-` style keys, any
`api_key=` assignment, and the literal values of the configured API-key environment variables. Petition text is never
passed to a logger by this code base; a `petition_text` extra field is additionally dropped as a safety net.
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from typing import Optional

_corr: contextvars.ContextVar[str] = contextvars.ContextVar("correlation_id", default="")
_run: contextvars.ContextVar[str] = contextvars.ContextVar("run_id", default="")

_PATTERNS = [re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}"), re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"),
             re.compile(r"(?i)(api[_-]?key|authorization|token|password|secret)(\"?\s*[:=]\s*\"?)[^\s\",}]{4,}")]
_SECRET_ENV = ("LLM_API_KEY", "FALLBACK_LLM_API_KEY")
_STD = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime", "taskName"}
_DROP = {"petition_text", "petition"}


def new_correlation_id() -> str:
    return uuid.uuid4().hex


def get_correlation_id() -> str:
    return _corr.get()


def set_context(correlation_id: Optional[str] = None, run_id: Optional[str] = None) -> None:
    if correlation_id is not None:
        _corr.set(correlation_id)
    if run_id is not None:
        _run.set(run_id)


def redact(text: str) -> str:
    for name in _SECRET_ENV:
        v = os.environ.get(name, "")
        if len(v) >= 6:
            text = text.replace(v, "[REDACTED]")
    text = _PATTERNS[0].sub("Bearer [REDACTED]", text)
    text = _PATTERNS[1].sub("[REDACTED]", text)
    return _PATTERNS[2].sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str):
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        d = {"ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
             "level": record.levelname, "service": self.service, "logger": record.name,
             "message": record.getMessage(), "correlation_id": _corr.get() or None, "run_id": _run.get() or None}
        for k, v in record.__dict__.items():
            if k not in _STD and k not in _DROP and not k.startswith("_"):
                d[k] = v
        if record.exc_info:
            d["exception"] = self.formatException(record.exc_info).splitlines()[-1]   # type + message only, no locals
        return redact(json.dumps(d, default=str, ensure_ascii=False))


def configure_logging(service: str, level: Optional[str] = None, stream=None) -> None:
    h = logging.StreamHandler(stream or sys.stdout)
    h.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    for old in list(root.handlers):
        root.removeHandler(old)
    root.addHandler(h)
    root.setLevel((level or os.environ.get("LOG_LEVEL", "INFO")).upper())
    for noisy in ("httpx", "httpx2", "httpcore", "huggingface_hub"):
        logging.getLogger(noisy).setLevel(logging.WARNING)       # these log full request URLs
