"""Idempotent ingestion: parse -> chunk -> diff against the index -> embed only new/changed -> upsert -> manifest.

Run:  python -m triage.retrieval.ingest [--force-rebuild] [--sources FILE ...]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import time
from typing import Optional

from .. import db
from ..config import Settings, get_settings
from .chunk import CHUNKER_VERSION, Chunk, chunk_document
from .embed import Embedder, EmbeddingError
from .parse import ParseError, parse_pdf
from .store import ChromaStore


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def discover_sources(corpus_dir: str) -> list[str]:
    return sorted(glob.glob(os.path.join(corpus_dir, "*.pdf")) + glob.glob(os.path.join(corpus_dir, "raw", "*.pdf")))


def check_verified_passages(spec_file: str, docs_pages: dict[str, dict[int, str]], chunks: list[Chunk]) -> tuple[dict, list[str]]:
    """A passage counts as verified only if its quote is in the source page text AND in an indexed chunk
    carrying the expected clause id. Nothing is assumed."""
    if not spec_file or not os.path.isfile(spec_file):
        return {}, [f"verified-passages file not found: {spec_file or '(unset)'}"]
    with open(spec_file, encoding="utf-8") as f:
        spec = json.load(f)
    out: dict[str, bool] = {}
    warns: list[str] = []
    for p in spec["passages"]:
        q = _norm(p["quote"])
        src_ok = q in _norm(docs_pages.get(p["doc_name"], {}).get(p["page"], ""))
        idx_ok = any(c.doc_name == p["doc_name"] and c.clause_id == p["clause_id"] and q in _norm(c.content)
                     and c.page_start <= p["page"] <= c.page_end for c in chunks)
        out[p["id"]] = src_ok and idx_ok
        if not out[p["id"]]:
            warns.append(f"verified passage {p['id']} ({p['clause_id']}, p{p['page']}): "
                         f"source_text={'ok' if src_ok else 'MISSING'}, indexed_chunk={'ok' if idx_ok else 'MISSING'}")
    return out, warns


def run_ingest(settings: Settings, embedder: Embedder, client, sources: Optional[list[str]] = None,
               force_rebuild: bool = False, record: bool = True) -> dict:
    started = db.now()
    t0 = time.time()
    manifest: dict = {"build_timestamp": started, "status": "failed", "chunker_version": CHUNKER_VERSION,
                      "documents": [], "chunks_total": 0, "new": 0, "updated": 0, "unchanged": 0, "removed": 0,
                      "embedded": 0, "warnings": [], "errors": [], "verified_passages": {}, "migrated_from": []}

    def finish(status: str) -> dict:
        manifest["status"] = status
        manifest["duration_seconds"] = round(time.time() - t0, 3)
        if record:
            db.save_ingest(settings.db_path, started, status, manifest)
        return manifest

    paths = sources or discover_sources(settings.corpus_dir)
    if not paths:
        manifest["errors"].append(f"no source PDFs found in {settings.corpus_dir}")
        return finish("failed")

    all_chunks: list[Chunk] = []
    pages: dict[str, dict[int, str]] = {}
    for p in paths:
        try:
            doc = parse_pdf(p)
        except ParseError as e:
            manifest["errors"].append(str(e))
            continue
        chunks, warns = chunk_document(doc)
        manifest["warnings"] += [f"{doc.doc_name}: {w}" for w in doc.warnings] + warns
        manifest["documents"].append({"doc_id": doc.doc_id, "file": doc.doc_name, "sha256": doc.sha256,
                                      "pages": doc.page_count, "chunks": len(chunks),
                                      "boilerplate_removed": doc.removed_boilerplate})
        pages[doc.doc_name] = doc.pages
        all_chunks += chunks
    if manifest["errors"]:  # never modify the index from a partial parse: stale-deletion would be wrong
        manifest["errors"].append("index left unchanged because at least one source failed to parse")
        return finish("failed")
    if not all_chunks:
        manifest["errors"].append("sources parsed but produced zero chunks")
        return finish("failed")

    try:
        tag = embedder.tag
    except EmbeddingError as e:
        manifest["errors"].append(str(e))
        return finish("failed")
    manifest["embedding_tag"] = tag
    store = ChromaStore(client, settings.chroma_collection, tag)
    manifest["collection"] = store.name
    try:
        if force_rebuild:
            store.reset()
        existing = store.existing()
        desired = {c.chunk_id: c for c in all_chunks}
        if len(desired) != len(all_chunks):
            manifest["warnings"].append("duplicate chunk ids collapsed (identical clause text)")
        stale = [i for i in existing if i not in desired]
        old_keys = {m.get("key") for i, m in existing.items() if i in stale}
        to_embed = [c for i, c in desired.items() if i not in existing]
        manifest["updated"] = sum(1 for c in to_embed if c.key in old_keys)
        manifest["new"] = len(to_embed) - manifest["updated"]
        manifest["unchanged"] = len(desired) - len(to_embed)
        manifest["removed"] = len(stale) - manifest["updated"]
        if stale:
            store.delete(stale)
        if to_embed:
            t1 = time.time()
            vecs = embedder.embed([c.embed_text() for c in to_embed])
            store.upsert(to_embed, vecs)
            el = max(time.time() - t1, 1e-6)
            manifest["embedded"] = len(to_embed)
            manifest["chunks_per_second"] = round(len(to_embed) / el, 2)
        manifest["chunks_total"] = store.count()
        # collections built with a different embedding configuration are removed only after this build succeeded
        old = store.other_collections()
        if old:
            store.drop_collections(old)
            manifest["migrated_from"] = old
            manifest["warnings"].append(f"removed collections built with another embedding config: {old}")
        if manifest["chunks_total"] != len(desired):
            manifest["errors"].append(f"index holds {manifest['chunks_total']} chunks, expected {len(desired)}")
            return finish("failed")
    except EmbeddingError as e:
        manifest["errors"].append(str(e))
        return finish("failed")
    except Exception as e:  # noqa: BLE001  (chroma unreachable etc.)
        manifest["errors"].append(f"index error: {type(e).__name__}: {e}")
        return finish("failed")

    vp, vwarn = check_verified_passages(settings.verified_passages_file, pages, all_chunks)
    manifest["verified_passages"] = vp
    manifest["warnings"] += vwarn
    return finish("success")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Idempotent corpus ingestion (parse, chunk, embed, index).")
    ap.add_argument("--force-rebuild", action="store_true", help="drop the current collection and re-embed everything")
    ap.add_argument("--sources", nargs="*", help="explicit PDF paths (default: corpus dir)")
    a = ap.parse_args(argv)
    s = get_settings()
    from .embed import SentenceTransformerEmbedder
    from .store import make_client
    try:
        client = make_client(s.chroma_host, s.chroma_port)
        client.heartbeat()
    except Exception as e:  # noqa: BLE001
        m = {"build_timestamp": db.now(), "status": "failed", "documents": [], "chunks_total": 0, "warnings": [],
             "errors": [f"Chroma unreachable at {s.chroma_host or '(CHROMA_HOST unset)'}:{s.chroma_port}: {type(e).__name__}"]}
        db.save_ingest(s.db_path, m["build_timestamp"], "failed", m)
        print(json.dumps(m, indent=2))
        return 1
    emb = SentenceTransformerEmbedder(s.embed_model, s.hf_home or None)
    m = run_ingest(s, emb, client, a.sources, a.force_rebuild)
    if m["status"] == "success":            # cached retrieval results belong to the previous corpus version
        try:
            from ..reliability.cache import invalidate_retrieval
            from ..reliability.deps import redis_for
            m["retrieval_cache_entries_removed"] = invalidate_retrieval(redis_for(s))
        except Exception as e:  # noqa: BLE001  (Redis optional here; fingerprinted keys are already version-safe)
            m["warnings"].append(f"retrieval cache not invalidated: {type(e).__name__}")
    print(json.dumps({k: v for k, v in m.items() if k != "documents"} | {"documents": [d["file"] for d in m["documents"]]},
                     indent=2))
    return 0 if m["status"] == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
