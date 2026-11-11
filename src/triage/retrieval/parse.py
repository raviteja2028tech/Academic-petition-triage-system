"""PDF parsing with PyMuPDF. Preserves PDF page numbers, reports (never hides) problems."""
from __future__ import annotations

import hashlib
import os
import re
from collections import Counter
from dataclasses import dataclass, field

SHORT_PAGE_CHARS = 200
_PAGE_NO = re.compile(r"^-\s*\d+\s*-$")


class ParseError(Exception):
    pass


@dataclass
class ParsedDoc:
    doc_id: str
    doc_name: str
    sha256: str
    page_count: int
    pages: dict[int, str]                       # raw text per 1-based PDF page
    lines: list[tuple[int, str]]                # cleaned (page, line) in reading order
    removed_boilerplate: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def make_doc_id(path: str) -> str:
    stem = os.path.splitext(os.path.basename(path))[0]
    return re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")


def parse_pdf(path: str) -> ParsedDoc:
    import pymupdf  # imported lazily so the API image does not need it

    if not os.path.isfile(path):
        raise ParseError(f"source not found: {path}")
    try:
        doc = pymupdf.open(path)
    except Exception as e:  # noqa: BLE001
        raise ParseError(f"cannot open {os.path.basename(path)} as PDF: {e}") from e
    if doc.page_count == 0:
        raise ParseError(f"{os.path.basename(path)} has no pages")

    pages = {i + 1: doc[i].get_text() for i in range(doc.page_count)}
    warnings: list[str] = []
    total = sum(len(t.strip()) for t in pages.values())
    if total == 0:
        raise ParseError(f"{os.path.basename(path)} has no text layer (scanned PDF? OCR required)")
    for n, t in pages.items():
        if len(t.strip()) < SHORT_PAGE_CHARS:
            warnings.append(f"page {n}: only {len(t.strip())} characters extracted (empty or suspiciously short)")

    # running headers / footers: lines that repeat on at least 40 % of pages
    counts: Counter[str] = Counter()
    for t in pages.values():
        counts.update({ln.strip() for ln in t.splitlines() if ln.strip()})
    threshold = max(3, int(0.4 * doc.page_count))
    boiler = {ln for ln, c in counts.items() if c >= threshold and len(ln) < 120}

    lines: list[tuple[int, str]] = []
    for n, t in pages.items():
        for ln in t.splitlines():
            s = re.sub(r"\s+", " ", ln).strip()
            if not s or s in boiler or _PAGE_NO.match(s):
                continue
            lines.append((n, s))
    return ParsedDoc(doc_id=make_doc_id(path), doc_name=os.path.basename(path), sha256=file_sha256(path),
                     page_count=doc.page_count, pages=pages, lines=lines,
                     removed_boilerplate=sorted(boiler), warnings=warnings)
