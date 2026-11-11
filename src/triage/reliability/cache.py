"""Redis caches for query embeddings and retrieval results.

Key design (version-bearing, so a changed configuration can never read an old entry):
  embedding:  emb:<sha(embedder.tag)>:<sha(text)>        tag = model name + dim + normalisation + chunker version
  retrieval:  ret:<corpus_fingerprint>:<sha(request)>     fingerprint = source-document sha256s + embedding tag +
                                                          chunker version + chunk count of the last successful ingestion
Prompts do not affect retrieval, so prompt versions are not in these keys. LLM responses are deliberately NOT cached
(a cached determination could be stale or detached from the verified evidence).
Invalidation: keys change automatically when documents / embedding config change; `invalidate_retrieval()` also deletes
old entries after an ingestion. Redis errors fall through to the real computation (a cache must never break a run).
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Callable, Optional

from .. import db
from ..retrieval.search import RetrievalResult
from .metrics import Metrics

log = logging.getLogger("triage.cache")


def _h(x: str) -> str:
    return hashlib.sha256(x.encode("utf-8")).hexdigest()[:24]


def corpus_fingerprint(db_path: str) -> str:
    """Identifies the exact indexed corpus; 'none' if nothing has been ingested successfully."""
    try:
        last = db.last_ingest(db_path, only_success=True)
    except Exception:  # noqa: BLE001
        return "none"
    if not last:
        return "none"
    m = last["manifest"]
    parts = [d.get("sha256", "") for d in sorted(m.get("documents", []), key=lambda d: d.get("file", ""))]
    return _h("|".join(parts + [m.get("embedding_tag", ""), m.get("chunker_version", ""), str(m.get("chunks_total", 0))]))


class CachedEmbedder:
    def __init__(self, inner, conn, metrics: Metrics, ttl: int = 3600):
        self.inner, self.conn, self.metrics, self.ttl = inner, conn, metrics, ttl

    @property
    def tag(self) -> str:
        return self.inner.tag

    def embed(self, texts: list[str]) -> list[list[float]]:
        prefix = f"emb:{_h(self.inner.tag)}:"
        out: list[Optional[list[float]]] = [None] * len(texts)
        miss: list[int] = []
        for i, t in enumerate(texts):
            try:
                raw = self.conn.get(prefix + _h(t))
            except Exception:  # noqa: BLE001
                raw = None
                self.metrics.inc("cache_errors_total", cache="embedding")
            if raw is not None:
                out[i] = json.loads(raw)
                self.metrics.inc("cache_hits_total", cache="embedding")
            else:
                miss.append(i)
                self.metrics.inc("cache_misses_total", cache="embedding")
        if miss:
            vecs = self.inner.embed([texts[i] for i in miss])
            for i, v in zip(miss, vecs):
                out[i] = v
                try:
                    self.conn.set(prefix + _h(texts[i]), json.dumps(v), ex=self.ttl)
                except Exception:  # noqa: BLE001
                    self.metrics.inc("cache_errors_total", cache="embedding")
        return out  # type: ignore[return-value]


class CachedRetriever:
    """Wraps a Retriever; caches semantic / keyword / clause lookups. Other attributes delegate to the inner one."""

    def __init__(self, inner, conn, metrics: Metrics, db_path: str, ttl: int = 3600,
                 fingerprint: Optional[Callable[[], str]] = None):
        self.inner, self.conn, self.metrics, self.ttl = inner, conn, metrics, ttl
        self._fp = fingerprint or (lambda: corpus_fingerprint(db_path))

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def _cached(self, kind: str, req: dict, compute: Callable[[], list[RetrievalResult]]) -> list[RetrievalResult]:
        fp = self._fp()
        if fp == "none":  # nothing known about the corpus version -> never serve from cache
            self.metrics.inc("cache_bypass_total", cache="retrieval")
            return compute()
        key = f"ret:{fp}:{_h(kind + json.dumps(req, sort_keys=True, default=str))}"
        try:
            raw = self.conn.get(key)
        except Exception:  # noqa: BLE001
            raw = None
            self.metrics.inc("cache_errors_total", cache="retrieval")
        if raw is not None:
            self.metrics.inc("cache_hits_total", cache="retrieval")
            return [RetrievalResult(**r) for r in json.loads(raw)]
        self.metrics.inc("cache_misses_total", cache="retrieval")
        res = compute()
        try:
            self.conn.set(key, json.dumps([r.model_dump() for r in res], default=str), ex=self.ttl)
        except Exception:  # noqa: BLE001
            self.metrics.inc("cache_errors_total", cache="retrieval")
        return res

    def semantic(self, query: str, k: int = 5, where: Optional[dict] = None):
        return self._cached("semantic", {"q": query, "k": k, "w": where}, lambda: self.inner.semantic(query, k, where))

    def hybrid(self, query: str, k: int = 5, where: Optional[dict] = None):
        return self._cached("hybrid", {"q": query, "k": k, "w": where}, lambda: self.inner.hybrid(query, k, where))

    def keyword(self, query: str, k: int = 5):
        return self._cached("keyword", {"q": query, "k": k}, lambda: self.inner.keyword(query, k))

    def by_clause_id(self, clause_id: str, include_children: bool = True):
        return self._cached("clause", {"c": clause_id, "ch": include_children},
                            lambda: self.inner.by_clause_id(clause_id, include_children))
    # get_chunk is intentionally NOT cached: citation verification must re-read the live index.


def invalidate_retrieval(conn) -> int:
    """Delete every cached retrieval result (called after an ingestion). Returns the number removed."""
    n = 0
    for k in conn.scan_iter(match="ret:*", count=500):
        conn.delete(k)
        n += 1
    return n
