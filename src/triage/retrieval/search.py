"""Retrieval strategies over the Chroma index. Plain Python callables; Phase 3 agents will wrap them as tools.

Strategies: semantic (embedding similarity), clause (direct id lookup), filter (metadata), keyword (BM25).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any, Optional

from pydantic import BaseModel

from .chunk import TOPIC_RULES, norm_clause_id
from .embed import Embedder
from .store import ChromaStore


class RetrievalResult(BaseModel):
    chunk_id: str
    text: str
    score: float
    strategy: str
    metadata: dict[str, Any]

    @property
    def citation(self) -> str:
        m = self.metadata
        return f"{m['doc_name']} · {m['chapter']} · {m['clause_id']} · p.{m['page_start']}"


def _res(items: list[dict], strategy: str, score: Optional[float] = None) -> list[RetrievalResult]:
    return [RetrievalResult(chunk_id=i["id"], text=i["text"], metadata=i["metadata"],
                            score=i.get("score", score if score is not None else 0.0), strategy=strategy)
            for i in items]


def _nat(cid: str) -> list:
    return [(0, int(t), "") if t.isdigit() else (1, 0, t) for t in re.findall(r"\d+|[A-Za-z]+", cid)]


def _tok(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", s.lower())


RRF_K = 60   # standard reciprocal-rank-fusion constant


def rrf_fuse(lists: list[list[RetrievalResult]], k: int) -> list[RetrievalResult]:
    """Reciprocal Rank Fusion: score(d) = sum over lists of 1 / (RRF_K + rank). A passage ranked well by BOTH the semantic and
    the BM25 retriever beats one that only a single retriever liked. Order among ties follows first appearance."""
    score: dict[str, float] = {}
    first: dict[str, RetrievalResult] = {}
    for lst in lists:
        for rank, r in enumerate(lst, start=1):
            score[r.chunk_id] = score.get(r.chunk_id, 0.0) + 1.0 / (RRF_K + rank)
            first.setdefault(r.chunk_id, r)
    ranked = sorted(score, key=lambda cid: -score[cid])[:k]
    return [first[c].model_copy(update={"score": round(score[c], 5), "strategy": "hybrid"}) for c in ranked]


class Retriever:
    def __init__(self, store: ChromaStore, embedder: Embedder):
        self.store, self.embedder = store, embedder
        self._bm25 = None
        self._bm25_docs: list[dict] = []

    def semantic(self, query: str, k: int = 5, where: Optional[dict] = None) -> list[RetrievalResult]:
        vec = self.embedder.embed([query])[0]
        return _res(self.store.query(vec, k, where), "semantic")

    def by_clause_id(self, clause_id: str, include_children: bool = True) -> list[RetrievalResult]:
        norm = norm_clause_id(clause_id)
        hits = self.store.get({"clause_norm": norm})
        if include_children and "(" not in norm:
            seen = {h["id"] for h in hits}
            hits += [h for h in self.store.get({"clause_root": norm}, limit=200) if h["id"] not in seen]
        hits.sort(key=lambda h: (h["metadata"]["page_start"], h["metadata"]["clause_id"]))
        return _res(hits, "clause", score=1.0)

    def filter(self, where: dict, limit: int = 50) -> list[RetrievalResult]:
        return _res(self.store.get(where, limit), "filter", score=0.0)

    def get_chunk(self, chunk_id: str) -> Optional[RetrievalResult]:
        """Re-read a chunk from the index by id (used to verify citations against the indexed text)."""
        hits = self.store.get_ids([chunk_id])
        return _res(hits, "chunk_id", score=1.0)[0] if hits else None

    def neighbours(self, clause_id: str, window: int = 1) -> list[RetrievalResult]:
        """Chunks immediately before/after the given clause within the same chapter, in document order."""
        targets = self.by_clause_id(clause_id, include_children=False)
        if not targets:
            return []
        chapter = targets[0].metadata["chapter"]
        sibs = self.store.get({"chapter": chapter}, limit=1000)
        sibs.sort(key=lambda h: (h["metadata"]["page_start"], _nat(h["metadata"]["clause_id"]), h["metadata"]["part"]))
        tid = {t.chunk_id for t in targets}
        idx = [i for i, h in enumerate(sibs) if h["id"] in tid]
        lo, hi = max(0, min(idx) - window), min(len(sibs), max(idx) + window + 1)
        out = [h for i, h in enumerate(sibs[lo:hi], start=lo) if h["id"] not in tid]
        return _res(out, "neighbour", score=0.0)

    def hybrid(self, query: str, k: int = 5, where: Optional[dict] = None) -> list[RetrievalResult]:
        """Semantic + BM25 fused with RRF (each retriever contributes its top 2k candidates)."""
        return rrf_fuse([self.semantic(query, 2 * k, where), self.keyword(query, 2 * k)], k)

    def keyword(self, query: str, k: int = 5) -> list[RetrievalResult]:
        from rank_bm25 import BM25Okapi
        if self._bm25 is None:
            self._bm25_docs = self.store.all()
            if not self._bm25_docs:
                return []
            self._bm25 = BM25Okapi([_tok(d["text"]) for d in self._bm25_docs])
        scores = self._bm25.get_scores(_tok(query))
        order = sorted(range(len(scores)), key=lambda i: -scores[i])[:k]
        return _res([{**self._bm25_docs[i], "score": float(scores[i])} for i in order if scores[i] > 0], "keyword")


def build_retriever_from_env() -> Retriever:
    from ..config import get_settings
    from .embed import SentenceTransformerEmbedder
    from .store import make_client
    s = get_settings()
    emb = SentenceTransformerEmbedder(s.embed_model, s.hf_home or None)
    return Retriever(ChromaStore(make_client(s.chroma_host, s.chroma_port), s.chroma_collection, emb.tag), emb)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Diagnostic retrieval CLI (not an agent).")
    ap.add_argument("query", help="query text, or a clause id with --strategy clause")
    ap.add_argument("--strategy", choices=["semantic", "keyword", "clause", "filter"], default="semantic")
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("--topic", choices=sorted(TOPIC_RULES), help="metadata filter on topic tag")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    r = build_retriever_from_env()
    where = {f"t_{a.topic}": True} if a.topic else None
    if a.strategy == "semantic":
        res = r.semantic(a.query, a.k, where)
    elif a.strategy == "keyword":
        res = r.keyword(a.query, a.k)
    elif a.strategy == "clause":
        res = r.by_clause_id(a.query)
    else:
        res = r.filter(where or {}, a.k)
    if a.json:
        print(json.dumps([x.model_dump() for x in res], indent=2))
    else:
        for x in res:
            print(f"[{x.strategy} {x.score:.3f}] {x.citation}\n    {x.text[:240]}\n")
        if not res:
            print("(no results)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
