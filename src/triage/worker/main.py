"""Worker entry point: JSON logging + tracing, then an RQ worker on the petitions queue.

WORKER_MODE=simple (default): jobs run inside the long-lived worker process, so the embedding model, BM25 index and
Chroma client are loaded ONCE per worker. WORKER_MODE=fork: stock RQ behaviour (a forked "work horse" per job): better
crash isolation, but every job reloads the embedding model (measured: ~10 s of the ~12 s per run; docs/LOAD_TEST.md).
Trade-off of simple mode: a hard crash (e.g. out-of-memory kill) takes down the worker (Docker restarts it) and memory
is not reclaimed between jobs. Job timeouts still apply (signal-based death penalty).
"""
from __future__ import annotations

import logging
import os

import redis
from rq import Queue, SimpleWorker, Worker

from ..config import get_settings
from ..observability import configure_logging, setup_tracing

log = logging.getLogger("triage.worker")


def main() -> None:
    configure_logging("worker")
    setup_tracing("triage-worker")
    s = get_settings()
    mode = os.environ.get("WORKER_MODE", "simple").lower()
    conn = redis.Redis.from_url(s.redis_url)
    if mode == "simple" and s.agent_mode != "placeholder":
        try:                                     # warm the model before the first job; failures are retried lazily per job
            from ..agents.runtime import make_retriever
            make_retriever(s)
            log.info("retriever warmed")
        except Exception as e:  # noqa: BLE001
            log.warning("retriever warm-up skipped: %s", type(e).__name__)
    cls = SimpleWorker if mode == "simple" else Worker
    log.info("worker starting", extra={"mode": mode})
    # worker_ttl=60: a killed worker disappears from the registry within ~a minute (default 420 s), so readiness counts live workers
    cls([Queue(s.queue_name, connection=conn)], connection=conn, worker_ttl=60).work(with_scheduler=False)


if __name__ == "__main__":
    main()
