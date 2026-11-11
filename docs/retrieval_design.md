# Retrieval design (L1, D2) — Phase 2

Code: `src/triage/retrieval/{parse,chunk,embed,store,search,ingest}.py`.

## Pipeline
`PDF → parse (PyMuPDF, per-page) → strip running headers/footers → skip table-of-contents pages → clause-aware chunks → diff against index → embed only new/changed → Chroma upsert → manifest (SQLite)`.

## Parsing
* PyMuPDF text per PDF page; page numbers preserved (for the VTU file, printed page = PDF page).
* Lines repeated on ≥40 % of pages (running header, footer date) and `- N -` page numbers are removed.
* Pages with <200 extracted characters raise a warning; a PDF with no text layer, an unreadable file or a missing file raises `ParseError`. Nothing is skipped silently.
* A failed source aborts the run **without touching the index** (otherwise stale-deletion would remove that document's chunks).

## Chunking (addresses the "condonation is elsewhere" difficulty)
* A section starts at each printed heading matching `25XX n.n…` (e.g. `25OB10.0 Attendance Requirement`). `chapter` = the nearest `n.0` heading.
* Sections with numbered/lettered top-level items `(1)…`/`(a)…` (detected in sequence so `(i)` is not mistaken for an item) are split into one chunk per item with the printed id, e.g. `25OB10.0(4)` and `25OB10.0(5)`. Short sections stay whole.
* Chunks > 1500 chars are split on line boundaries (`part` > 1).
* Front matter without clause numbers gets labelled fallback ids (`NOID-p6`, `PREAMBLE(1.4)`), with `id_inferred=true`.
* Each chunk keeps `doc_id, doc_name, doc_version (sha256 prefix), page_start/end, chapter, section, clause_id, text_hash, content, topics`. The embedded text is `breadcrumb + content` (doc › chapter › clause), the stored/cited text is the content alone.
* Topic tags (regex rules: attendance, condonation, medical, discretion, exemption, eligibility) become boolean metadata (`t_condonation` …) for filtered search.
* Chunk id = sha1(doc_id | clause_id | part | content hash). The **key** (doc|clause|part) identifies "the same clause"; a different hash with the same key means *updated*.

### Known limitations (inspected on the real VTU PDF: 197 chunks, 20 with inferred ids)
* Contents pages 2–5 are detected and excluded.
* Front-matter text is chunked per page, so `PREAMBLE(1.4)` also contains the start of "Definition of Key Words" that follows on the same page.
* Headings wrapped over two lines keep only the first line as title; tables (Table 25OB23.0.1) are flattened into one text chunk.
* Revaluation and change-of-branch annexures listed in the contents are not in the supplied PDF.

## Embeddings
* Local sentence-transformers, model name from `EMBED_MODEL`; cached under `HF_HOME` (Docker volume `hf_cache`) so it downloads once.
* Clear `EmbeddingError` when the name is unset, the model cannot be loaded (offline/unknown) or memory is insufficient.
* The **embedding tag** `st|<model>|dim<N>|norm|<chunker version>` names the Chroma collection (`<base>_<sha1(tag)[:8]>`).

## Index, idempotency, re-embedding
* Chroma server (cosine space). Upserts by stable id.
* Re-running with unchanged inputs: 0 embeddings (`unchanged = all`). Changed clause: old id deleted, new id embedded (`updated=1`). Removed clause: deleted (`removed`). Verified by tests with a counting embedder.
* Changed embedding configuration → new collection, full re-embed, then the old collection is dropped (`migrated_from` in the manifest); vectors of different dimension are never mixed.
* `--force-rebuild` drops and rebuilds the current collection.
* Manifest (table `ingest_runs`): build time, per-document sha256/pages/chunks, counts new/updated/unchanged/removed/embedded, chunks/second, embedding tag, warnings, errors, verified-passage results.

## Verified passages
`corpus/verified_passages.json` lists quotes read from the PDF (see `docs/corpus_verification.md`). Ingestion marks a passage verified only if the quote is in that page's source text **and** in an indexed chunk with the stated clause id. The result feeds `GET /v1/corpus`.

## Retrieval API (`search.py`)
`Retriever.semantic / keyword (BM25) / by_clause_id (exact + children) / filter (metadata)` → `RetrievalResult{chunk_id, text, score, strategy, metadata}`.
CLI: `python -m triage.retrieval.search "query" [--strategy semantic|keyword|clause|filter] [--topic condonation] [-k 5] [--json]`.
These are plain functions; they are **not** agent-controlled yet (Phase 3).

## Measured on the real corpus (all-MiniLM-L6-v2, tests/test_real_model.py)
* Natural query "minimum attendance percentage required in a course" → `25OB10.0(4)` in top-5.
* Derived query "shortage of attendance may be condoned on medical grounds by the Vice-Chancellor" → `25OB10.0(5)` in top-5.
* Petition-style question "My attendance is 80 percent…" → top-5 `[25OB23.0, 25OB12.0, 25OB10.0(4), 25OB10.0(5), 25OB8.2]` (both clauses present, but ranked 3rd and 4th, behind unrelated hits). This is a single observation, not a recall figure; no recall metric is claimed.

## Phase 4-5 additions
* **Caching.** Query embeddings and retrieval results (semantic / keyword / clause) are cached in Redis; keys carry the embedding tag and a corpus fingerprint (document SHA-256s + embedding tag + chunker version + chunk count of the last *successful* ingestion), so a changed document, embedding configuration or chunker can never read an old entry; ingestion also deletes `ret:*`. `get_chunk` (citation verification) is never cached. See `docs/reliability.md`.
* **Tool validation.** Arguments to the retrieval tools are validated and bounded before execution (`k` 1-8, query <= 300 chars, clause-id pattern, topic from the known set).
* **Measured behaviour** (`docs/evaluation.md`, experiment 1, real `all-MiniLM-L6-v2` embeddings, 6 query phrasings): semantic search places the condonation clause 25OB10.0(5) in the top 5 for 5/6 phrasings but both the base rule 25OB10.0(4) and the condonation clause in the same top 5 only 4/6 times; BM25 keyword search finds 25OB10.0(5) in only 2/6. A second, mechanically derived query did not change these counts. This is why the Research agent uses `get_clause` / `get_neighbouring_clauses`, and why the verifier insists that every citation was actually retrieved in the run.
* **Known weakness:** precision. With `k=5`, many returned passages belong to other attendance-related clauses (context relevance 0.414 in the scripted evaluation).
