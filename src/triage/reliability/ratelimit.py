"""Redis fixed-window rate limiter, per client. Returns what the API needs for a meaningful HTTP 429."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable


@dataclass
class RateDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int  # seconds until the window resets


def check_rate(conn, client: str, limit: int, window: int, clock: Callable[[], float] = time.time) -> RateDecision:
    now = clock()
    bucket = int(now // window)
    key = f"rl:{client}:{bucket}"
    n = conn.incr(key)
    if n == 1:
        conn.expire(key, window + 1)
    reset = max(1, int((bucket + 1) * window - now + 0.999))
    return RateDecision(n <= limit, limit, max(0, limit - n), reset)
