"""Phase 2 tests.

Two groups:
  * SYNTHETIC fixtures (tests below, clearly labelled): exercise the pipeline mechanics only.
    The fixture text is invented test data and is NOT VTU regulation text.
  * REAL corpus tests (class TestRealCorpus): use the supplied VTU PDF.
"""
import json
import os
import uuid

import chromadb
import pymupdf
import pytest

from triage import db
from triage.config import Settings
from triage.retrieval.chunk import chunk_document
from triage.retrieval.embed import EmbeddingError, HashEmbedder, SentenceTransformerEmbedder
from triage.retrieval.ingest import run_ingest
from triage.retrieval.parse import ParseError, parse_pdf
from triage.retrieval.search import Retriever
from triage.retrieval.store import ChromaStore

REAL_PDF = os.path.join(os.path.dirname(__file__), "..", "corpus", "VTU B.Tech. Regulations 2025.pdf")
VERIFIED = os.path.join(os.path.dirname(__file__), "..", "corpus", "verified_passages.json")

SYNTH_V1 = [
    ("25OB1.0 Alpha Rule", ["SYNTHETIC TEST FIXTURE - NOT REAL REGULATIONS.",
                            "(1) Widgets must be registered before the first of the month by every member.",
                            "(2) A registration fee of seven tokens applies to every widget registered.",
                            "(3) Late registration is possible with written approval of the fixture board."]),
    ("25OB2.0 Beta Exception", ["The fixture board may waive the late registration of widgets in rare cases",
                                "when a member provides valid synthetic proof of an emergency situation."]),
]


def make_pdf(path, sections, filler_pages=0):
    doc = pymupdf.open()
    page = doc.new_page()
    y = 60
    for head, lines in sections:
        for text in [head] + lines:
            page.insert_text((40, y), text, fontsize=9)
            y += 14
        y += 8
    for i in range(filler_pages):
        doc.new_page().insert_text((40, 60), f"filler page {i} " * 30, fontsize=9)
    doc.save(str(path))
    doc.close()
    return str(path)


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.sqlite3"))
    monkeypatch.setenv("CHROMA_COLLECTION", "t" + uuid.uuid4().hex[:8])
    monkeypatch.setenv("CORPUS_DIR", str(tmp_path / "corpus"))
    monkeypatch.setenv("VERIFIED_PASSAGES_FILE", "")
    (tmp_path / "corpus").mkdir()
    return Settings()


@pytest.fixture
def client():
    return chromadb.EphemeralClient()


# ------------------------------------------------------------------ parsing
def test_parse_preserves_pages_and_hash(tmp_path):
    p = make_pdf(tmp_path / "syn.pdf", SYNTH_V1, filler_pages=2)
    d = parse_pdf(p)
    assert d.page_count == 3 and set(d.pages) == {1, 2, 3}
    assert len(d.sha256) == 64 and d.doc_id == "syn"
    assert all(pg in (1, 2, 3) for pg, _ in d.lines)


def test_parse_errors_are_reported_not_silent(tmp_path):
    with pytest.raises(ParseError, match="not found"):
        parse_pdf(str(tmp_path / "missing.pdf"))
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"this is not a pdf")
    with pytest.raises(ParseError):
        parse_pdf(str(bad))
    empty = pymupdf.open()
    empty.new_page()
    empty.save(str(tmp_path / "blank.pdf"))
    with pytest.raises(ParseError, match="no text layer"):
        parse_pdf(str(tmp_path / "blank.pdf"))


def test_short_pages_are_warned(tmp_path):
    p = make_pdf(tmp_path / "syn.pdf", SYNTH_V1)
    doc = pymupdf.open(p)
    doc.new_page().insert_text((40, 60), "tiny", fontsize=9)
    doc.saveIncr()
    doc.close()
    warns = parse_pdf(p).warnings
    assert any(w.startswith("page 2") and "suspiciously short" in w for w in warns)
    assert not any(w.startswith("page 1") for w in warns)


# ------------------------------------------------------------------ chunking
def test_clause_aware_chunks_and_stable_ids(tmp_path):
    p = make_pdf(tmp_path / "syn.pdf", SYNTH_V1)
    c1, _ = chunk_document(parse_pdf(p))
    c2, _ = chunk_document(parse_pdf(p))
    assert [c.chunk_id for c in c1] == [c.chunk_id for c in c2]
    assert len({c.chunk_id for c in c1}) == len(c1)
    ids = {c.clause_id for c in c1}
    assert {"25OB1.0(1)", "25OB1.0(2)", "25OB1.0(3)", "25OB2.0"} <= ids
    c = next(c for c in c1 if c.clause_id == "25OB1.0(2)")
    assert c.page_start == c.page_end == 1 and c.chapter.startswith("25OB1.0") and not c.id_inferred
    assert len(c.text_hash) == 64 and c.doc_version.startswith("sha256:")


def test_unidentified_text_gets_labelled_fallback_ids(tmp_path):
    p = make_pdf(tmp_path / "syn.pdf", [("Introduction", ["Text without any printed clause numbering at all here."])])
    chunks, _ = chunk_document(parse_pdf(p))
    assert chunks and all(c.id_inferred and c.clause_id.startswith("NOID-p1") for c in chunks)


# ------------------------------------------------------------------ store + retrieval
def build(settings, client, tmp_path, name="syn.pdf", sections=SYNTH_V1):
    p = make_pdf(tmp_path / "corpus" / name, sections)
    m = run_ingest(settings, HashEmbedder(), client, [p])
    assert m["status"] == "success", m
    return p, m


def retriever(settings, client):
    emb = HashEmbedder()
    return Retriever(ChromaStore(client, settings.chroma_collection, emb.tag), emb)


def test_ingest_then_retrieve_all_strategies(settings, client, tmp_path):
    _, m = build(settings, client, tmp_path)
    assert m["chunks_total"] == 5 and m["new"] == 5 and m["unchanged"] == 0
    r = retriever(settings, client)
    top = r.semantic("fee applies to every widget registered", k=2)
    assert top[0].metadata["clause_id"] == "25OB1.0(2)" and top[0].strategy == "semantic"
    assert {"chunk_id", "text", "score", "strategy", "metadata"} <= set(top[0].model_dump())
    assert r.keyword("waive late registration emergency", k=1)[0].metadata["clause_id"] == "25OB2.0"
    assert [x.metadata["clause_id"] for x in r.by_clause_id("25ob1.0(2)")] == ["25OB1.0(2)"]
    assert len(r.by_clause_id("25OB1.0")) == 4                      # parent id returns its intro + 3 items
    assert r.by_clause_id("99ZZ1.0") == []
    assert {x.metadata["clause_id"] for x in r.filter({"t_eligibility": False, "clause_root": "25ob2.0"})} == {"25OB2.0"}


def test_idempotent_reingest(settings, client, tmp_path):
    p, _ = build(settings, client, tmp_path)
    class Counting(HashEmbedder):
        calls = 0
        def embed(self, texts):
            Counting.calls += len(texts)
            return super().embed(texts)
    m2 = run_ingest(settings, Counting(), client, [p])
    assert m2["status"] == "success" and Counting.calls == 0
    assert (m2["new"], m2["updated"], m2["unchanged"], m2["removed"], m2["embedded"]) == (0, 0, 5, 0, 0)
    assert ChromaStore(client, settings.chroma_collection, HashEmbedder().tag).count() == 5


def test_changed_chunk_updates_only_that_chunk(settings, client, tmp_path):
    build(settings, client, tmp_path)
    changed = [(SYNTH_V1[0][0], [SYNTH_V1[0][1][0], SYNTH_V1[0][1][1],
                                 "(2) A registration fee of NINE tokens applies to every widget registered.",
                                 SYNTH_V1[0][1][3]]), SYNTH_V1[1]]
    p = make_pdf(tmp_path / "corpus" / "syn.pdf", changed)
    m = run_ingest(settings, HashEmbedder(), client, [p])
    assert (m["updated"], m["new"], m["removed"], m["embedded"], m["unchanged"]) == (1, 0, 0, 1, 4)
    r = retriever(settings, client)
    texts = [x.text for x in r.by_clause_id("25OB1.0(2)")]
    assert len(texts) == 1 and "NINE" in texts[0] and "seven" not in texts[0]


def test_removed_chunk_is_not_retrievable(settings, client, tmp_path):
    build(settings, client, tmp_path)
    p = make_pdf(tmp_path / "corpus" / "syn.pdf", [SYNTH_V1[0]])
    m = run_ingest(settings, HashEmbedder(), client, [p])
    assert m["removed"] == 1 and m["chunks_total"] == 4
    r = retriever(settings, client)
    assert r.by_clause_id("25OB2.0") == []
    assert all(x.metadata["clause_id"] != "25OB2.0" for x in r.keyword("waive late registration emergency", k=5))


def test_embedding_config_change_migrates_collection_without_mixing(settings, client, tmp_path):
    p, _ = build(settings, client, tmp_path)
    small = HashEmbedder(dim=32, name="other")
    m = run_ingest(settings, small, client, [p])
    assert m["status"] == "success" and m["embedded"] == 5 and m["chunks_total"] == 5
    assert len(m["migrated_from"]) == 1
    names = [c if isinstance(c, str) else c.name for c in client.list_collections()
             if (c if isinstance(c, str) else c.name).startswith(settings.chroma_collection)]
    assert len(names) == 1                                   # old-dimension collection removed
    r = Retriever(ChromaStore(client, settings.chroma_collection, small.tag), small)
    assert r.semantic("registration fee", k=1)[0].metadata["clause_id"]


def test_force_rebuild_reembeds_everything(settings, client, tmp_path):
    p, _ = build(settings, client, tmp_path)
    m = run_ingest(settings, HashEmbedder(), client, [p], force_rebuild=True)
    assert m["embedded"] == 5 and m["new"] == 5 and m["chunks_total"] == 5


def test_empty_corpus_and_missing_source_fail_loudly(settings, client):
    m = run_ingest(settings, HashEmbedder(), client)           # corpus dir exists but is empty
    assert m["status"] == "failed" and "no source PDFs" in m["errors"][0]
    m = run_ingest(settings, HashEmbedder(), client, ["nope.pdf"])
    assert m["status"] == "failed" and "not found" in m["errors"][0]
    assert db.last_ingest(settings.db_path)["status"] == "failed"


def test_corrupt_source_leaves_existing_index_untouched(settings, client, tmp_path):
    p, _ = build(settings, client, tmp_path)
    bad = tmp_path / "corpus" / "bad.pdf"
    bad.write_bytes(b"garbage")
    m = run_ingest(settings, HashEmbedder(), client, [p, str(bad)])
    assert m["status"] == "failed" and any("left unchanged" in e for e in m["errors"])
    assert ChromaStore(client, settings.chroma_collection, HashEmbedder().tag).count() == 5


def test_missing_embedding_model_is_clear_error():
    with pytest.raises(EmbeddingError, match="EMBED_MODEL is not set"):
        SentenceTransformerEmbedder("")
    with pytest.raises(EmbeddingError, match="cannot load embedding model"):
        SentenceTransformerEmbedder("definitely/not-a-real-model-xyz", "./.nocache").tag


def test_verified_passages_checked_against_source_and_index(settings, client, tmp_path, monkeypatch):
    spec = tmp_path / "vp.json"
    spec.write_text(json.dumps({"passages": [
        {"id": "ok", "doc_name": "syn.pdf", "page": 1, "clause_id": "25OB1.0(2)", "quote": "fee of seven tokens"},
        {"id": "wrong-clause", "doc_name": "syn.pdf", "page": 1, "clause_id": "25OB1.0(1)", "quote": "fee of seven tokens"},
        {"id": "absent", "doc_name": "syn.pdf", "page": 1, "clause_id": "25OB1.0(2)", "quote": "fee of nine hundred tokens"}]}))
    monkeypatch.setenv("VERIFIED_PASSAGES_FILE", str(spec))
    _, m = build(Settings(), client, tmp_path)
    assert m["verified_passages"] == {"ok": True, "wrong-clause": False, "absent": False}
    assert len([w for w in m["warnings"] if "verified passage" in w]) == 2


# ------------------------------------------------------------------ corpus status API
def test_corpus_api_reports_failure_not_ready(settings, client, tmp_path, monkeypatch):
    from triage.api import main as api
    run_ingest(settings, HashEmbedder(), client)              # fails: empty corpus
    monkeypatch.setattr(api, "_chroma_reachable", lambda s: True)
    st = api.build_corpus_status(settings)
    assert st.ready is False and st.last_attempt_status == "failed" and st.errors and st.index_exists is False


def test_corpus_api_ready_after_successful_ingest(settings, client, tmp_path, monkeypatch):
    from triage.api import main as api
    build(settings, client, tmp_path)
    monkeypatch.setattr(api, "_chroma_reachable", lambda s: True)
    st = api.build_corpus_status(settings)
    assert st.ready and st.chunks_indexed == 5 and st.documents_indexed == 1 and st.index_exists
    monkeypatch.setattr(api, "_chroma_reachable", lambda s: False)
    assert api.build_corpus_status(settings).ready is False   # index recorded but Chroma down


# ------------------------------------------------------------------ REAL corpus
@pytest.fixture(scope="module")
def real_chunks():
    d = parse_pdf(REAL_PDF)
    chunks, warns = chunk_document(d)
    return d, chunks, warns


class TestRealCorpus:
    def test_text_layer_pages_and_checksum(self, real_chunks):
        d, _, _ = real_chunks
        assert d.page_count == 41
        assert d.sha256 == "7969bb7d2b8269f3169ff5a480d2da4bf46800aabb454b4fece47f38679c6436"
        assert "Attendance Requirement" in d.pages[18]            # PDF page == printed page
        assert "may be condoned by the Vice-Chancellor" in " ".join(d.pages[19].split())

    def test_verified_clauses_are_chunked_with_correct_ids_and_pages(self, real_chunks):
        _, chunks, _ = real_chunks
        by = {c.clause_id: c for c in chunks}
        base, cond = by["25OB10.0(4)"], by["25OB10.0(5)"]
        assert "minimum attendance of 85 %" in base.content and base.page_start == 18
        assert "condoned by the Vice-Chancellor" in cond.content and "Medical reasons" in cond.content
        assert cond.page_start == 19 and {"condonation", "medical", "attendance"} <= set(cond.topics)
        assert base.chapter.startswith("25OB10.0")

    def test_every_verified_passage_resolves_in_source_and_chunks(self, real_chunks):
        d, chunks, _ = real_chunks
        vp, warns = check_vp(d, chunks)
        assert vp and all(vp.values()), warns

    def test_toc_pages_skipped_and_chunk_ids_unique(self, real_chunks):
        _, chunks, warns = real_chunks
        assert any("table of contents" in w for w in warns)
        assert min(c.page_start for c in chunks if not c.id_inferred) > 5
        assert len({c.chunk_id for c in chunks}) == len(chunks)

    def test_hash_embedder_pipeline_on_real_pdf_is_idempotent_and_clause_lookup_works(self, settings, client):
        m1 = run_ingest(settings, HashEmbedder(), client, [REAL_PDF])
        m2 = run_ingest(settings, HashEmbedder(), client, [REAL_PDF])
        assert m1["status"] == m2["status"] == "success" and m2["embedded"] == 0
        assert m2["unchanged"] == m1["chunks_total"]
        r = retriever(settings, client)
        got = r.by_clause_id("25OB10.0")
        assert {x.metadata["clause_id"] for x in got} >= {"25OB10.0(4)", "25OB10.0(5)"}
        # lexical retrieval of the condonation clause does not depend on the neural model
        assert "25OB10.0(5)" in [x.metadata["clause_id"] for x in r.keyword("shortage condoned Vice-Chancellor medical", k=3)]


def check_vp(d, chunks):
    from triage.retrieval.ingest import check_verified_passages
    return check_verified_passages(VERIFIED, {d.doc_name: d.pages}, chunks)
