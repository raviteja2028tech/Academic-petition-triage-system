"""Clause-aware chunking.

A chunk is one printed clause (heading section) or, for long sections made of numbered/lettered
items, one top-level item such as 25OB10.0(5). Clause ids are copied from the printed text;
where none can be identified a clearly labelled fallback id is used and `id_inferred` is set.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Optional

from .parse import ParsedDoc

CHUNKER_VERSION = "clause-v1"
MAX_CHARS = 1500
HEADING = re.compile(r"^(25[A-Z]{1,3}\s?\d+(?:\.\d+)*)\s*(.*)$")
MARKER = re.compile(r"^\(\s?(\d{1,2}|[a-z])\s?\)")
PREAMBLE_MARKER = re.compile(r"^\((\d+\.\d+)\)")
ANY_MARKER = re.compile(r"^\(\s?[0-9a-zA-Z.]{1,5}\s?\)")

TOPIC_RULES = {
    "attendance": r"attendance|\bDX\b",
    "condonation": r"condon",
    "medical": r"medical|health",
    "discretion": r"discretion|Vice-Chancellor|final and binding",
    "exemption": r"exempt",
    "eligibility": r"eligible|permitted to appear|shall not be permitted",
}


@dataclass
class Chunk:
    chunk_id: str
    key: str
    doc_id: str
    doc_name: str
    doc_version: str
    page_start: int
    page_end: int
    chapter: str
    section: str
    clause_id: str
    id_inferred: bool
    part: int
    text_hash: str
    content: str
    breadcrumb: str
    topics: list[str] = field(default_factory=list)

    def embed_text(self) -> str:
        return f"{self.breadcrumb}\n{self.content}"

    def metadata(self) -> dict:
        m = {k: v for k, v in asdict(self).items() if k not in ("content", "topics")}
        m["topics"] = ",".join(self.topics)
        for t in TOPIC_RULES:
            m[f"t_{t}"] = t in self.topics
        m["clause_root"] = norm_clause_id(self.clause_id.split("(")[0])
        m["clause_norm"] = norm_clause_id(self.clause_id)
        return m


def norm_clause_id(s: str) -> str:
    return re.sub(r"\s+", "", s).lower()


def _topics(text: str) -> list[str]:
    return [t for t, rx in TOPIC_RULES.items() if re.search(rx, text, re.I)]


def _join(lines: list[str]) -> str:
    out: list[str] = []
    for ln in lines:
        if out and not ANY_MARKER.match(ln):
            out[-1] += " " + ln
        else:
            out.append(ln)
    return "\n".join(out)


def _split_long(text: str) -> list[str]:
    if len(text) <= MAX_CHARS:
        return [text]
    parts, cur = [], ""
    for para in text.split("\n"):
        if cur and len(cur) + len(para) + 1 > MAX_CHARS:
            parts.append(cur)
            cur = para
        else:
            cur = f"{cur}\n{para}" if cur else para
    if cur:
        parts.append(cur)
    return parts


def _toc_pages(doc: ParsedDoc) -> set[int]:
    by_page: dict[int, list[str]] = {}
    for p, ln in doc.lines:
        by_page.setdefault(p, []).append(ln)
    out = set()
    for p, lns in by_page.items():
        if len(lns) >= 8 and sum(bool(HEADING.match(x)) for x in lns) / len(lns) >= 0.4:
            out.add(p)
    return out


def chunk_document(doc: ParsedDoc) -> tuple[list[Chunk], list[str]]:
    warnings: list[str] = []
    toc = _toc_pages(doc)
    if toc:
        warnings.append(f"{doc.doc_name}: pages {sorted(toc)} look like a table of contents and were not indexed")
    version = f"sha256:{doc.sha256[:12]}"

    # 1. split into sections by printed headings
    sections: list[dict] = []
    cur: Optional[dict] = None
    chapter = ""
    for page, ln in doc.lines:
        if page in toc:
            continue
        m = HEADING.match(ln)
        if m and not m.group(2).startswith(")") and (not m.group(2) or not m.group(2)[0].islower()):
            hid = re.sub(r"\s+", "", m.group(1))
            title = m.group(2).strip()
            label = f"{hid} {title}".strip()
            if re.search(r"\d+\.0$", hid):
                chapter = label
            cur = {"id": hid, "label": label, "chapter": chapter or label, "inferred": False, "lines": []}
            sections.append(cur)
            continue
        if cur is None:
            cur = {"id": None, "label": "Front matter / preamble", "chapter": "Front matter / preamble",
                   "inferred": True, "lines": []}
            sections.append(cur)
        cur["lines"].append((page, ln))

    # 2. split each section into items and build chunks
    chunks: list[Chunk] = []
    seen: dict[str, int] = {}

    def emit(clause_id: str, inferred: bool, sec: dict, lines: list[tuple[int, str]]) -> None:
        if not lines:
            return
        text = _join([t for _, t in lines]).strip()
        if len(text) < 20:
            return
        for part, piece in enumerate(_split_long(text), start=1):
            key = f"{doc.doc_id}|{clause_id}|{part}"
            seen[key] = seen.get(key, 0) + 1
            if seen[key] > 1:
                key += f"~{seen[key]}"
            th = hashlib.sha256(piece.encode()).hexdigest()
            cid = hashlib.sha1(f"{key}|{th}".encode()).hexdigest()[:20]
            sec_label = sec["label"] if sec["id"] else ""
            chunks.append(Chunk(
                chunk_id=cid, key=key, doc_id=doc.doc_id, doc_name=doc.doc_name, doc_version=version,
                page_start=lines[0][0], page_end=lines[-1][0], chapter=sec["chapter"], section=sec_label,
                clause_id=clause_id, id_inferred=inferred, part=part, text_hash=th, content=piece,
                breadcrumb=" > ".join(x for x in (doc.doc_name.rsplit(".", 1)[0], sec["chapter"],
                                                  sec_label if sec_label != sec["chapter"] else "",
                                                  clause_id if clause_id != sec["id"] else "") if x),
                topics=_topics(piece)))

    for sec in sections:
        lines = sec["lines"]
        if sec["id"] is None:  # front matter: one chunk per page, or per (1.4)-style preamble item
            by_unit: list[tuple[str, list[tuple[int, str]]]] = []
            for page, ln in lines:
                pm = PREAMBLE_MARKER.match(ln)
                if pm:
                    by_unit.append((f"PREAMBLE({pm.group(1)})", [(page, ln)]))
                elif by_unit and by_unit[-1][0].startswith("PREAMBLE(") and by_unit[-1][1][-1][0] == page:
                    by_unit[-1][1].append((page, ln))
                elif by_unit and by_unit[-1][0] == f"NOID-p{page}":
                    by_unit[-1][1].append((page, ln))
                else:
                    by_unit.append((f"NOID-p{page}", [(page, ln)]))
            for cid, ls in by_unit:
                emit(cid, True, sec, ls)
            continue
        # top-level items: expected-sequence matching avoids treating (i) or (ii) as new items
        items: list[tuple[str, list[tuple[int, str]]]] = [("", [])]
        expected: Optional[str] = None
        for page, ln in lines:
            m = MARKER.match(ln)
            take = False
            if m:
                tok = m.group(1)
                if expected is None:
                    take = tok in ("1", "a")
                else:
                    take = tok == expected
                if take:
                    expected = str(int(tok) + 1) if tok.isdigit() else chr(ord(tok) + 1)
            if take:
                items.append((m.group(1), [(page, ln)]))
            else:
                items[-1][1].append((page, ln))
        if len(items) == 1 or sum(len(x) for _, ls in items for _, x in ls) <= 200:
            emit(sec["id"], False, sec, [x for _, ls in items for x in ls])
            continue
        emit(sec["id"], False, sec, items[0][1])  # intro text before item (1)/(a)
        for tok, ls in items[1:]:
            emit(f"{sec['id']}({tok})", False, sec, ls)

    if not chunks:
        warnings.append(f"{doc.doc_name}: no chunks produced")
    return chunks, warnings
