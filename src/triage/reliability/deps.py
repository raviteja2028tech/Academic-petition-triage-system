"""Shared Redis connection for reliability features. Tests monkeypatch `redis_for`."""
from __future__ import annotations

import time

import redis

from ..config import Settings

_cache: dict[str, redis.Redis] = {}

# When Redis is unreachable every call would otherwise wait for its connect timeout (2 s) - and the API makes several per request,
# inside an async event loop, so even /healthz stalled (found by loadtest/failure_drills.py). Callers record a failure here and
# skip optional Redis work (metrics, rate limiting) for a short window; mandatory work (queueing) fails fast with a clear error.
REDIS_DOWN_WINDOW = 5.0
_down_until = 0.0


def mark_redis_down(seconds: float = REDIS_DOWN_WINDOW) -> None:
    global _down_until
    _down_until = time.time() + seconds


def redis_recently_down() -> bool:
    return time.time() < _down_until


def reset_redis_state() -> None:
    global _down_until
    _down_until = 0.0


def redis_for(s: Settings) -> redis.Redis:
    if s.redis_url not in _cache:
        _cache[s.redis_url] = redis.Redis.from_url(s.redis_url, socket_connect_timeout=2, socket_timeout=2)
    return _cache[s.redis_url]
