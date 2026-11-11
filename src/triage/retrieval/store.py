"""Chroma wrapper. One collection per embedding configuration tag, so vectors of different
dimensions/models are never mixed in the same collection."""
from __future__ import annotations

import hashlib
from typing import Any, Optional

from .chunk import Chunk

BATCH = 200


def make_client(host: str, port: int):
    import chromadb
    if not host:
        raise RuntimeError("CHROMA_HOST is not set")
    return chromadb.HttpClient(host=host, port=port)


def _where(d: Optional[dict]) -> Optional[dict]:
    if not d:
        return None
    if len(d) == 1:
        return d
    return {"$and": [{k: v} for k, v in d.items()]}


class ChromaStore:
    def __init__(self, client, base_name: str, embedding_tag: str):
        self.client, self.base, self.tag = client, base_name, embedding_tag
        self.name = f"{base_name}_{hashlib.sha1(embedding_tag.encode()).hexdigest()[:8]}"
        self.col = client.get_or_create_collection(
            self.name, metadata={"hnsw:space": "cosine", "embedding_tag": embedding_tag})

    # ---- maintenance ----
    def health(self) -> dict:
        try:
            self.client.heartbeat()
            return {"ok": True, "collection": self.name, "count": self.col.count()}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def other_collections(self) -> list[str]:
        return [c if isinstance(c, str) else c.name for c in self.client.list_collections()
                if (c if isinstance(c, str) else c.name).startswith(self.base + "_")
                and (c if isinstance(c, str) else c.name) != self.name]

    def drop_collections(self, names: list[str]) -> None:
        for n in names:
            self.client.delete_collection(n)

    def reset(self) -> None:
        self.client.delete_collection(self.name)
        self.col = self.client.get_or_create_collection(
            self.name, metadata={"hnsw:space": "cosine", "embedding_tag": self.tag})

    def count(self) -> int:
        return self.col.count()

    # ---- contents ----
    def existing(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        offset = 0
        while True:
            r = self.col.get(include=["metadatas"], limit=1000, offset=offset)
            if not r["ids"]:
                break
            out.update(dict(zip(r["ids"], r["metadatas"])))
            offset += len(r["ids"])
        return out

    def delete(self, ids: list[str]) -> None:
        for i in range(0, len(ids), BATCH):
            self.col.delete(ids=ids[i:i + BATCH])

    def upsert(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        assert len(chunks) == len(embeddings)
        for i in range(0, len(chunks), BATCH):
            cs = chunks[i:i + BATCH]
            self.col.upsert(ids=[c.chunk_id for c in cs], embeddings=embeddings[i:i + BATCH],
                            documents=[c.content for c in cs], metadatas=[c.metadata() for c in cs])

    # ---- reads ----
    def query(self, embedding: list[float], k: int, where: Optional[dict] = None) -> list[dict]:
        n = self.col.count()
        if n == 0:
            return []
        r = self.col.query(query_embeddings=[embedding], n_results=min(k, n), where=_where(where),
                           include=["documents", "metadatas", "distances"])
        return [{"id": i, "text": d, "metadata": m, "score": 1.0 - float(dist)}
                for i, d, m, dist in zip(r["ids"][0], r["documents"][0], r["metadatas"][0], r["distances"][0])]

    def get(self, where: Optional[dict] = None, limit: int = 100) -> list[dict]:
        r = self.col.get(where=_where(where), include=["documents", "metadatas"], limit=limit)
        return [{"id": i, "text": d, "metadata": m} for i, d, m in zip(r["ids"], r["documents"], r["metadatas"])]

    def get_ids(self, ids: list[str]) -> list[dict]:
        r = self.col.get(ids=ids, include=["documents", "metadatas"])
        return [{"id": i, "text": d, "metadata": m} for i, d, m in zip(r["ids"], r["documents"], r["metadatas"])]

    def all(self) -> list[dict]:
        out, offset = [], 0
        while True:
            r = self.col.get(include=["documents", "metadatas"], limit=1000, offset=offset)
            if not r["ids"]:
                return out
            out += [{"id": i, "text": d, "metadata": m} for i, d, m in zip(r["ids"], r["documents"], r["metadatas"])]
            offset += len(r["ids"])
