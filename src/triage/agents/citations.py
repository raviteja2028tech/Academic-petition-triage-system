"""Citation verification (A3). A citation is accepted only if it resolves to text that was retrieved in this run
AND is still present, unchanged, in the index. Document/clause/page in the output come from the index, never the model."""
from __future__ import annotations

import re
from typing import Callable, Optional

from ..retrieval.chunk import norm_clause_id
from .context import EvidenceRegistry
from .state import Citation, CitationIn

MIN_QUOTE_CHARS = 15


def _squash(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _exact_span(quote: str, text: str) -> Optional[str]:
    words = quote.split()
    if not words:
        return None
    m = re.search(r"\s+".join(re.escape(w) for w in words), text, re.I)
    return m.group(0) if m else None


def verify_citations(cits: list[CitationIn], registry: EvidenceRegistry,
                     get_indexed_text: Callable[[str], Optional[str]]) -> tuple[list[Citation], list[dict]]:
    ok: list[Citation] = []
    bad: list[dict] = []
    for c in cits:
        def fail(why: str) -> None:
            bad.append({"evidence_id": c.evidence_id, "clause_id": c.clause_id, "quote": c.quote[:120], "why": why})

        ev = registry.by_id.get(c.evidence_id)
        if ev is None:
            fail("evidence_id was not retrieved in this run")
            continue
        if c.clause_id and norm_clause_id(c.clause_id) != norm_clause_id(ev["clause_id"]):
            fail(f"claimed clause {c.clause_id} but that passage is {ev['clause_id']}")
            continue
        if len(c.quote.strip()) < MIN_QUOTE_CHARS:
            fail(f"quote shorter than {MIN_QUOTE_CHARS} characters")
            continue
        span = _exact_span(c.quote.strip().strip('"“”'), ev["text"])
        if span is None:
            fail("quote is not contained in the retrieved passage")
            continue
        indexed = get_indexed_text(ev["chunk_id"])
        if indexed is None or _squash(indexed) != _squash(ev["text"]):
            fail("passage missing from, or different in, the index")
            continue
        ok.append(Citation(evidence_id=c.evidence_id, chunk_id=ev["chunk_id"], document=ev["doc_name"],
                           chapter=ev["chapter"], clause_id=ev["clause_id"], page=ev["page_start"], quote=span))
    return ok, bad
