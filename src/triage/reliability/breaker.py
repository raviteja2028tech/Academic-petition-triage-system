"""Redis-backed circuit breaker (closed -> open -> half-open -> closed), shared by every worker process.

closed:    calls allowed; consecutive failures counted.
open:      calls rejected until `cooldown` has passed since opening.
half_open: one probe call is admitted at a time (SET NX lock); success closes, failure re-opens.
Only provider-outage failures should be recorded (the caller decides); auth/invalid-request errors are not outages.
"""
from __future__ import annotations

import time
from typing import Callable, Optional

CLOSED, OPEN, HALF_OPEN = "closed", "open", "half_open"


class CircuitBreaker:
    def __init__(self, conn, name: str, failure_threshold: int = 5, cooldown: float = 30.0,
                 clock: Callable[[], float] = time.time,
                 on_transition: Optional[Callable[[str, str, str], None]] = None):
        self.conn, self.name = conn, name
        self.threshold, self.cooldown, self.clock = failure_threshold, cooldown, clock
        self.on_transition = on_transition
        self.key, self.probe_key = f"cb:{name}", f"cb:{name}:probe"

    def _get(self) -> dict:
        h = {k.decode(): v.decode() for k, v in self.conn.hgetall(self.key).items()}
        return {"state": h.get("state", CLOSED), "failures": int(h.get("failures", 0)),
                "opened_at": float(h.get("opened_at", 0))}

    def _set(self, state: str, **kw) -> None:
        old = self._get()["state"]
        self.conn.hset(self.key, mapping={"state": state, **{k: str(v) for k, v in kw.items()}})
        if old != state and self.on_transition:
            self.on_transition(self.name, old, state)

    @property
    def state(self) -> str:
        """Effective state (an expired 'open' reads as half_open)."""
        st = self._get()
        if st["state"] == OPEN and self.clock() - st["opened_at"] >= self.cooldown:
            return HALF_OPEN
        return st["state"]

    def allow(self) -> bool:
        st = self._get()
        if st["state"] == CLOSED:
            return True
        if st["state"] == OPEN:
            if self.clock() - st["opened_at"] < self.cooldown:
                return False
            self._set(HALF_OPEN)
        # half-open: a single probe at a time; the lock expires so a crashed probe cannot wedge the breaker
        return bool(self.conn.set(self.probe_key, "1", nx=True, ex=max(1, int(self.cooldown))))

    def record_success(self) -> None:
        st = self._get()
        if st["state"] != CLOSED:
            self._set(CLOSED, failures=0)
        elif st["failures"]:
            self.conn.hset(self.key, "failures", "0")
        self.conn.delete(self.probe_key)

    def record_failure(self) -> None:
        st = self._get()
        if st["state"] == HALF_OPEN:
            self._set(OPEN, opened_at=self.clock(), failures=st["failures"])
            self.conn.delete(self.probe_key)
            return
        n = st["failures"] + 1
        if n >= self.threshold:
            self._set(OPEN, opened_at=self.clock(), failures=n)
        else:
            self.conn.hset(self.key, "failures", str(n))

    def reset(self) -> None:
        self.conn.delete(self.key, self.probe_key)
