"""Minimal provider-neutral LLM client (OpenAI-compatible chat API over HTTP).

Provider, endpoint, key and model come only from environment variables (LLM_BASE_URL, LLM_API_KEY,
LLM_MODEL). Every call has a timeout and failures are classified (kind/retryable). Retry, circuit breaker and fallback live in
triage.reliability.resilient_llm, which wraps this client.
"""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional, Protocol

import httpx

from ..config import Settings


class LLMError(Exception):
    """Provider failure (HTTP error, timeout, malformed response).

    kind: timeout | connection | rate_limit | server | auth | client | invalid_response | circuit_open | error
    retryable: only transient outage kinds (timeout, connection, rate_limit, server) are retried.
    """

    def __init__(self, msg: str, kind: str = "error", retryable: bool = False,
                 retry_after: Optional[float] = None, provider: str = ""):
        super().__init__(msg)
        self.kind, self.retryable, self.retry_after, self.provider = kind, retryable, retry_after, provider


class CircuitOpen(LLMError):
    """Every configured provider is currently short-circuited by its breaker."""

    def __init__(self, msg: str):
        super().__init__(msg, kind="circuit_open", retryable=False)


class LLMNotConfigured(LLMError):
    """No LLM provider is configured."""


@dataclass
class LLMResponse:
    text: str
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    model: str = ""
    latency_s: float = 0.0
    provider: str = ""


class LLMClient(Protocol):
    def complete(self, role: str, system: str, user: str, timeout: float) -> LLMResponse: ...


def _provider_message(resp: "httpx.Response", api_key: str = "") -> str:
    """Short, secret-free provider error text (OpenAI-style {"error": {"message": ...}}) for diagnosis."""
    try:
        msg = (resp.json().get("error") or {}).get("message") or resp.text
    except Exception:  # noqa: BLE001
        msg = resp.text
    msg = " ".join(str(msg).split())[:240]
    return msg.replace(api_key, "<redacted>") if api_key else msg


# Some hosted chat models treat the action names in our prompts as native function calls and the
# provider then rejects the reply with HTTP 400 "Tool choice is none, but model called a tool". This note, appended to
# every system message, keeps the model in plain-text JSON mode. Verified against the real provider (see docs).
PLAIN_JSON_NOTE = ("\n\nOUTPUT FORMAT: you have NO native function-calling ability in this conversation. Names such as "
                   "tools or actions in the instructions above are only labels that application code will execute for "
                   "you. Never emit a tool or function call; reply as plain assistant text containing exactly one "
                   "JSON object.")

_TRY_AGAIN = re.compile(r"try again in\s+(?:(\d+)m)?\s*(\d+(?:\.\d+)?)s", re.I)


def _retry_after(resp: "httpx.Response") -> Optional[float]:
    """Seconds to wait before retrying a 429: Retry-After header, else the provider's 'try again in 1m2.5s' text."""
    ra = resp.headers.get("retry-after", "")
    if ra.replace(".", "", 1).isdigit():
        return float(ra)
    m = _TRY_AGAIN.search(resp.text or "")
    return (int(m.group(1) or 0) * 60 + float(m.group(2))) if m else None


# --- proactive pacing for tokens-per-minute limits -------------------------------------------------------------------
# Providers report the remaining token budget in x-ratelimit-* headers. Waiting a few seconds BEFORE a call that would
# not fit is far cheaper than sending it, receiving a 429 and spending a retry (and run budget) on it. Per process.
_pace_lock = threading.Lock()
_pace: dict[str, tuple[float, float, float]] = {}      # base_url -> (remaining_tokens, limit_tokens, observed_at)
PACE_MAX_WAIT = 30.0
QUOTA_WAIT_THRESHOLD = 90.0   # a 429 asking for more than this is a quota, not a burst limit: do not wait for it inside a run


def _note_rate_headers(base_url: str, headers) -> None:
    try:
        rem, lim = float(headers.get("x-ratelimit-remaining-tokens", "")), float(headers.get("x-ratelimit-limit-tokens", ""))
    except (TypeError, ValueError):
        return
    with _pace_lock:
        _pace[base_url] = (rem, lim, time.time())


def _pace_wait(base_url: str, est_tokens: float) -> float:
    """Seconds to wait so the estimated request fits the provider's refilling token bucket (0 when unknown / enough)."""
    with _pace_lock:
        st = _pace.get(base_url)
    if not st:
        return 0.0
    rem, lim, seen = st
    if lim <= 0:
        return 0.0
    refilled = rem + (time.time() - seen) * lim / 60.0          # buckets are per minute and refill continuously
    deficit = est_tokens - min(lim, refilled)
    return min(PACE_MAX_WAIT, deficit * 60.0 / lim) if deficit > 0 else 0.0


class OpenAICompatClient:
    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url, self.api_key, self.model = base_url.rstrip("/"), api_key, model

    def complete(self, role: str, system: str, user: str, timeout: float) -> LLMResponse:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body = {"model": self.model, "temperature": 0,
                "messages": [{"role": "system", "content": system + PLAIN_JSON_NOTE}, {"role": "user", "content": user}]}
        wait = _pace_wait(self.base_url, (len(system) + len(PLAIN_JSON_NOTE) + len(user)) / 3.2 + 500)
        if wait > 0:
            time.sleep(wait)
        t0 = time.time()
        try:
            r = httpx.post(f"{self.base_url}/chat/completions", headers=headers, json=body, timeout=timeout)
            _note_rate_headers(self.base_url, r.headers)
            r.raise_for_status()
            data = r.json()
            text = data["choices"][0]["message"]["content"] or ""
        except httpx.TimeoutException as e:
            raise LLMError(f"LLM call timed out after {timeout}s", "timeout", True) from e
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            if code == 429:
                wait = _retry_after(e.response)
                if wait is not None and wait > QUOTA_WAIT_THRESHOLD:
                    # The provider wants minutes, not seconds (e.g. a tokens-per-DAY quota). Waiting inside this run would only burn
                    # its whole time budget, so fail fast with the provider's own explanation; the run escalates to a human.
                    raise LLMError(f"LLM provider quota exhausted (HTTP 429, retry in {int(wait)}s): "
                                   f"{_provider_message(e.response, self.api_key)}", "quota", False, wait) from e
                raise LLMError("LLM provider rate limit (HTTP 429)", "rate_limit", True, wait) from e
            if code >= 500:
                raise LLMError(f"LLM provider error (HTTP {code})", "server", True) from e
            if code in (401, 403):
                raise LLMError(f"LLM provider rejected credentials (HTTP {code})", "auth", False) from e
            detail = _provider_message(e.response, self.api_key)
            if code == 400 and "model called a tool" in detail.lower():
                # stochastic model glitch (observed with a small hosted model): the reply was a native tool call. Retry; not an outage.
                raise LLMError(f"LLM provider returned HTTP 400: {detail}", "model_tool_call", True) from e
            raise LLMError(f"LLM provider returned HTTP {code}: {detail}", "client", False) from e
        except httpx.TransportError as e:
            raise LLMError(f"LLM connection failed: {type(e).__name__}", "connection", True) from e
        except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError) as e:
            raise LLMError(f"LLM returned an unusable response: {type(e).__name__}", "invalid_response", False) from e
        usage = data.get("usage") or {}
        return LLMResponse(text=text, prompt_tokens=usage.get("prompt_tokens"),
                           completion_tokens=usage.get("completion_tokens"),
                           model=data.get("model", self.model), latency_s=time.time() - t0)


def build_client(s: Settings) -> LLMClient:
    if not s.llm_base_url or not s.llm_model:
        raise LLMNotConfigured("No LLM provider configured: set LLM_BASE_URL, LLM_MODEL (and LLM_API_KEY if "
                               "the provider needs one) in your private .env")
    return OpenAICompatClient(s.llm_base_url, s.llm_api_key, s.llm_model)


def extract_json(text: str) -> Any:
    """Parse the first JSON object in a model reply (tolerates code fences and surrounding prose)."""
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.S)
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        raise ValueError("no JSON object found in model output")
    return json.loads(t[i:j + 1])
