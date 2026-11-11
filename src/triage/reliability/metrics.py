"""Cross-process counters and latency histograms stored in a Redis hash (API and workers are separate processes).

Metrics must never break petition processing: every Redis error is swallowed. Rendered as Prometheus text by the API.
"""
from __future__ import annotations

import logging
from typing import Optional

from .deps import mark_redis_down, redis_recently_down

log = logging.getLogger("triage.metrics")
KEY = "triage:metrics"
BUCKETS = (0.1, 0.5, 1, 2, 5, 10, 30, 60, 120)


def _name(metric: str, labels: dict) -> str:
    lab = ",".join('%s="%s"' % (k, str(v).replace('"', "")) for k, v in sorted(labels.items()))
    return "%s{%s}" % (metric, lab) if lab else metric


class Metrics:
    def __init__(self, conn):
        self.conn = conn

    def inc(self, metric: str, n: float = 1, **labels) -> None:
        if redis_recently_down():
            return
        try:
            self.conn.hincrbyfloat(KEY, _name(metric, labels), n)
        except Exception as e:  # noqa: BLE001
            mark_redis_down()
            log.debug("metric inc failed: %s", type(e).__name__)

    def observe(self, metric: str, value: float, **labels) -> None:
        """Histogram: <metric>_bucket{le=..}, _sum, _count (cumulative buckets, Prometheus style)."""
        if redis_recently_down():
            return
        try:
            p = self.conn.pipeline()
            for b in BUCKETS:
                if value <= b:
                    p.hincrbyfloat(KEY, _name(metric + "_bucket", {**labels, "le": b}), 1)
            p.hincrbyfloat(KEY, _name(metric + "_bucket", {**labels, "le": "+Inf"}), 1)
            p.hincrbyfloat(KEY, _name(metric + "_sum", labels), value)
            p.hincrbyfloat(KEY, _name(metric + "_count", labels), 1)
            p.execute()
        except Exception as e:  # noqa: BLE001
            mark_redis_down()
            log.debug("metric observe failed: %s", type(e).__name__)

    def snapshot(self) -> dict[str, float]:
        try:
            return {k.decode(): float(v) for k, v in self.conn.hgetall(KEY).items()}
        except Exception:  # noqa: BLE001
            return {}

    def render_prometheus(self) -> str:
        """Prometheus text exposition: one `# TYPE` line per metric family, samples grouped under it."""
        fams: dict[str, list[str]] = {}
        for k, v in sorted(self.snapshot().items()):
            base = k.split("{", 1)[0]
            fam = base
            for suf in ("_bucket", "_sum", "_count"):
                if base.endswith(suf):
                    fam = base[: -len(suf)]
            fams.setdefault(fam, []).append("%s %g" % (k, v))
        out: list[str] = []
        for fam, samples in fams.items():
            kind = "histogram" if any(s.startswith(fam + "_bucket") for s in samples) else (
                "counter" if fam.endswith("_total") else "untyped")
            out += ["# TYPE %s %s" % (fam, kind)] + samples
        return "\n".join(out) + ("\n" if out else "")


_override: Optional[Metrics] = None


def get_metrics(settings=None) -> Metrics:
    if _override is not None:
        return _override
    from ..config import get_settings
    from .deps import redis_for
    return Metrics(redis_for(settings or get_settings()))


def set_metrics(m: Optional[Metrics]) -> None:
    global _override
    _override = m
