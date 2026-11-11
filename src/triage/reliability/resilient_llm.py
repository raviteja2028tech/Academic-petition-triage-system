"""Resilient LLM wrapper: per-provider retry with backoff, Redis circuit breaker, optional fallback provider.

Order: for each provider (primary, then fallback if configured) -> breaker.allow()? -> call with bounded retry.
Retryable = timeout / connection / 429 / 5xx. Non-retryable errors (auth, 4xx, unusable response) are raised
immediately for that provider (never silently retried); the next provider may still be tried.
Only outage-type failures (retryable kinds, after retries are exhausted) count toward the breaker.
If nothing can answer, the original error (or CircuitOpen) is raised and the agent graph escalates; this class never
fabricates a response.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Callable, Optional

from ..config import Settings
from ..llm.client import CircuitOpen, LLMClient, LLMError, LLMNotConfigured, LLMResponse, OpenAICompatClient
from .breaker import CircuitBreaker
from .metrics import Metrics, get_metrics
from .retry import call_with_retry

OUTAGE_KINDS = {"timeout", "connection", "rate_limit", "server", "quota"}


@dataclass
class Provider:
    name: str
    client: LLMClient


class ResilientLLM:
    def __init__(self, providers: list[Provider], breakers: dict[str, CircuitBreaker], metrics: Metrics,
                 max_attempts: int = 3, backoff_base: float = 0.5, backoff_cap: float = 8.0,
                 rate_limit_attempts: int = 8, sleep: Callable[[float], None] = time.sleep, rng: Optional[random.Random] = None):
        self.providers, self.breakers, self.metrics = providers, breakers, metrics
        self.max_attempts, self.base, self.cap = max_attempts, backoff_base, backoff_cap
        self.rate_limit_attempts = rate_limit_attempts
        self.sleep, self.rng = sleep, rng or random.Random()
        self.sink: Optional[Callable[..., None]] = None          # ctx.record, set by the runtime
        self.remaining: Optional[Callable[[], float]] = None      # run time budget, set by the runtime

    def _emit(self, event: str, **kw) -> None:
        if self.sink:
            try:
                self.sink(event, **kw)
            except Exception:  # noqa: BLE001
                pass

    def complete(self, role: str, system: str, user: str, timeout: float) -> LLMResponse:
        last: Optional[Exception] = None
        skipped_open = 0
        for i, p in enumerate(self.providers):
            br = self.breakers[p.name]
            if not br.allow():
                skipped_open += 1
                self.metrics.inc("llm_breaker_rejected_total", provider=p.name)
                self._emit("llm_skipped", provider=p.name, reason="circuit_open")
                continue
            if i > 0:
                self.metrics.inc("llm_fallback_used_total", provider=p.name)
                self._emit("llm_fallback", provider=p.name)

            def on_retry(n: int, e: Exception, d: float, _p=p) -> None:
                self.metrics.inc("llm_retries_total", provider=_p.name, kind=getattr(e, "kind", "error"))
                self._emit("llm_retry", provider=_p.name, attempt=n, kind=getattr(e, "kind", "error"),
                           delay_s=round(d, 3))

            t0 = time.time()
            try:
                r = call_with_retry(lambda _p=p: _p.client.complete(role, system, user, timeout),
                                    max_attempts=self.max_attempts, base=self.base, cap=self.cap,
                                    sleep=self.sleep, rng=self.rng, remaining=self.remaining,
                                    rate_limit_attempts=self.rate_limit_attempts, on_retry=on_retry)
            except LLMError as e:
                e.provider = e.provider or p.name
                last = e
                outage = e.kind in OUTAGE_KINDS
                if outage:
                    br.record_failure()
                self.metrics.inc("llm_calls_total", provider=p.name, outcome=e.kind)
                self.metrics.observe("llm_call_seconds", time.time() - t0, provider=p.name)
                continue
            br.record_success()
            r.provider = p.name
            self.metrics.inc("llm_calls_total", provider=p.name, outcome="ok")
            self.metrics.observe("llm_call_seconds", time.time() - t0, provider=p.name)
            return r
        if last is not None:
            raise last
        raise CircuitOpen("LLM unavailable: circuit breaker is open for every configured provider; "
                          "no reliable reasoning is available, escalating without a determination")


def breaker_for(conn, name: str, s: Settings, metrics: Metrics) -> CircuitBreaker:
    return CircuitBreaker(conn, name, s.breaker_failure_threshold, s.breaker_cooldown_seconds,
                          on_transition=lambda n, old, new: metrics.inc("llm_breaker_transitions_total",
                                                                       provider=n, to=new))


def build_resilient(s: Settings, conn=None, metrics: Optional[Metrics] = None) -> ResilientLLM:
    """Primary (+ optional fallback) from settings. Raises LLMNotConfigured when no primary is configured."""
    if not s.llm_base_url or not s.llm_model:
        raise LLMNotConfigured("No LLM provider configured: set LLM_BASE_URL, LLM_MODEL (and LLM_API_KEY if "
                               "the provider needs one) in your private .env")
    if conn is None:
        from .deps import redis_for
        conn = redis_for(s)
    metrics = metrics or get_metrics(s)
    providers = [Provider("primary", OpenAICompatClient(s.llm_base_url, s.llm_api_key, s.llm_model))]
    if s.fallback_llm_base_url and s.fallback_llm_model:
        providers.append(Provider("fallback", OpenAICompatClient(s.fallback_llm_base_url, s.fallback_llm_api_key,
                                                                  s.fallback_llm_model)))
    breakers = {p.name: breaker_for(conn, p.name, s, metrics) for p in providers}
    return ResilientLLM(providers, breakers, metrics, s.llm_max_attempts, s.llm_backoff_base_seconds,
                        s.llm_backoff_cap_seconds, s.llm_rate_limit_max_attempts)
