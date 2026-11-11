"""Bounded retry with exponential backoff and full jitter. Only errors flagged `retryable` are retried."""
from __future__ import annotations

import random
import time
from typing import Callable, Optional, TypeVar

T = TypeVar("T")
RETRY_AFTER_CAP = 30.0   # provider-requested waits (e.g. tokens-per-minute limits) may exceed the jitter cap, up to this


def backoff_delay(attempt: int, base: float, cap: float, rng: random.Random, retry_after: Optional[float] = None) -> float:
    """attempt = number of the try that just failed (1-based). Full jitter: U(0, min(cap, base*2^(n-1))).
    A provider Retry-After is honoured as a lower bound (still capped)."""
    d = rng.uniform(0, min(cap, base * (2 ** (attempt - 1))))
    if retry_after:
        d = max(d, min(retry_after, max(cap, RETRY_AFTER_CAP)))
    return d


def call_with_retry(fn: Callable[[], T], *, max_attempts: int, base: float, cap: float,
                    sleep: Callable[[float], None] = time.sleep, rng: Optional[random.Random] = None,
                    remaining: Optional[Callable[[], float]] = None, rate_limit_attempts: Optional[int] = None,
                    on_retry: Optional[Callable[[int, Exception, float], None]] = None) -> T:
    """Runs fn; on an exception with `.retryable` true, sleeps and retries up to max_attempts total tries.
    Never retries non-retryable errors, and never sleeps past the caller's remaining time budget."""
    rng = rng or random.Random()
    attempt = 0
    while True:
        attempt += 1
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            limit = rate_limit_attempts if (rate_limit_attempts and getattr(e, "kind", "") == "rate_limit") else max_attempts
            if not getattr(e, "retryable", False) or attempt >= limit:
                raise
            d = backoff_delay(attempt, base, cap, rng, getattr(e, "retry_after", None))
            if remaining is not None and d >= remaining():
                raise  # waiting would exhaust the run budget; surface the real error now
            if on_retry:
                on_retry(attempt, e, d)
            sleep(d)
