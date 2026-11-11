"""Retrieval quality on the REAL VTU corpus with the real local embedding model.

Needs EMBED_MODEL in the environment (see .env.example) and either network access for the first download
or a populated HF cache. Skipped, not faked, when unavailable. Only gold clauses verified in
docs/corpus_verification.md are used.
"""
import os
import uuid

import chromadb
import pytest

from triage.config import Settings
from triage.retrieval.embed import EmbeddingError, SentenceTransformerEmbedder
from triage.retrieval.ingest import run_ingest
from triage.retrieval.search import Retriever
from triage.retrieval.store import ChromaStore

REAL_PDF = os.path.join(os.path.dirname(__file__), "..", "corpus", "VTU B.Tech. Regulations 2025.pdf")
pytestmark = pytest.mark.realmodel


@pytest.fixture(scope="module")
def real_index(tmp_path_factory):
    name = os.environ.get("EMBED_MODEL", "")
    if not name:
        pytest.skip("EMBED_MODEL not set")
    emb = SentenceTransformerEmbedder(name, os.environ.get("HF_HOME") or None)
    try:
        emb.tag
    except EmbeddingError as e:
        pytest.skip(f"embedding model unavailable: {e}")
    tmp = tmp_path_factory.mktemp("real")
    os.environ["DB_PATH"] = str(tmp / "t.sqlite3")
    os.environ["CHROMA_COLLECTION"] = "r" + uuid.uuid4().hex[:8]
    os.environ["VERIFIED_PASSAGES_FILE"] = os.path.join(os.path.dirname(__file__), "..", "corpus", "verified_passages.json")
    client = chromadb.EphemeralClient()
    s = Settings()
    m = run_ingest(s, emb, client, [REAL_PDF])
    assert m["status"] == "success", m
    return Retriever(ChromaStore(client, s.chroma_collection, emb.tag), emb), m


def ids(res):
    return [r.metadata["clause_id"] for r in res]


def test_manifest_and_verified_passages(real_index):
    _, m = real_index
    assert m["chunks_total"] > 150 and m["embedded"] == m["chunks_total"] and m["chunks_per_second"] > 0
    assert m["verified_passages"] and all(m["verified_passages"].values()), m["warnings"]


def test_base_rule_retrieved_by_natural_query(real_index):
    r, _ = real_index
    assert "25OB10.0(4)" in ids(r.semantic("What is the minimum attendance percentage required in a course?", k=5))


def test_condonation_clause_retrieved_by_derived_query(real_index):
    """The single-pass query about attendance may return only the base rule; a second query derived from
    what was read ('shortage ... condoned') must surface the condonation clause."""
    r, _ = real_index
    assert "25OB10.0(5)" in ids(r.semantic("shortage of attendance may be condoned on medical grounds by the Vice-Chancellor", k=5))


def test_report_single_pass_recall_for_the_difficult_case(real_index, capsys):
    """Diagnostic, not an assertion about product quality: records whether ONE pass on the petition-style
    question finds BOTH required clauses (the assignment says it usually will not)."""
    r, _ = real_index
    got = ids(r.semantic("My attendance is 80 percent in a course. Am I eligible to write the exam?", k=5))
    print("single-pass top-5:", got)
    assert "25OB10.0(4)" in got or "25OB10.0(5)" in got or "25OB10.0(7)" in got
