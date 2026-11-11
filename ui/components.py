"""Reusable UI components. Pure functions returning HTML strings (or Altair charts); no API access, no business logic.
Every dynamic value is HTML-escaped: model-written text (basis, quotes) must never be able to inject markup."""
from __future__ import annotations

from html import escape as _e
from typing import Iterable, Optional

import altair as alt

from style import CHART, TOKENS


def esc(v) -> str:
    return _e("" if v is None else str(v), quote=True)


# --- inline icons (Lucide-style strokes, 24x24) ---
_ICONS = {
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "alert": '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
    "x": '<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6M9 9l6 6"/>',
    "info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
    "file": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>',
}


def icon(name: str, size: int = 18) -> str:
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{_ICONS[name]}</svg>')


BRAND_MARK = ('<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#FAF8F4" stroke-width="1.8" stroke-linecap="round" '
              'stroke-linejoin="round" aria-hidden="true"><path d="M5 4h10l4 4v12H5z"/><path d="M9 12h6M9 16h4"/>'
              '<path d="M15 4v4h4" stroke="#5EC4B6"/></svg>')


def brand() -> str:
    return (f'<div class="brand"><div class="brand-mark">{BRAND_MARK}</div><div><div class="brand-name">Petition Triage</div>'
            f'<div class="brand-sub">Academic regulations</div></div></div>')


# --- text-level components ---
def badge(status: str, label: Optional[str] = None, dot: bool = True) -> str:
    kind = {"queued": "queued", "running": "running", "completed": "completed", "escalated": "escalated", "failed": "failed"}.get(status, status)
    d = '<span class="d"></span>' if dot else ""
    return f'<span class="badge b-{esc(kind)}">{d}{esc(label if label is not None else status)}</span>'


def page_header(title: str, subtitle: str = "", eyebrow: str = "", rule: bool = True) -> str:
    eb = f'<div class="eyebrow">{esc(eyebrow)}</div>' if eyebrow else ""
    sub = f"<p>{esc(subtitle)}</p>" if subtitle else ""
    return f'<div class="ph{"" if rule else " norule"}"><div>{eb}<h1>{esc(title)}</h1>{sub}</div></div>'


def section(title: str, hint: str = "") -> str:
    h = f'<span class="hint">{esc(hint)}</span>' if hint else ""
    return f'<div class="sec"><h2>{esc(title)}</h2>{h}</div>'


def stat_strip(items: Iterable[tuple]) -> str:
    """items: (value, label[, emphasise])."""
    cells = "".join(f'<div class="s{" emph" if (len(i) > 2 and i[2]) else ""}"><div class="v">{esc(i[0])}</div><div class="l">{esc(i[1])}</div></div>'
                    for i in items)
    return f'<div class="strip">{cells}</div>'


def alert(kind: str, title: str, body: str = "") -> str:
    ic = {"info": "info", "ok": "check", "warn": "alert", "bad": "x", "na": "info"}[kind]
    b = f"<span>{esc(body)}</span>" if body else ""
    return f'<div class="alert {kind}" role="status">{icon(ic)}<div><b>{esc(title)}</b>{b}</div></div>'


def empty_state(title: str, body: str = "") -> str:
    return f'<div class="empty"><b>{esc(title)}</b>{esc(body)}</div>'


def dot(kind: str) -> str:
    return f'<span class="dot {kind}" aria-hidden="true"></span>'


def kv(rows: Iterable[tuple]) -> str:
    return '<dl class="kv">' + "".join(f"<dt>{esc(k)}</dt><dd>{v}</dd>" for k, v in rows) + "</dl>"  # v is pre-escaped HTML


def table(columns: list[str], rows: list[list[str]], numeric: Optional[set] = None) -> str:
    """rows hold ready HTML cells (use esc() / badge() when building them)."""
    numeric = numeric or set()
    head = "".join(f'<th class="{"num" if i in numeric else ""}">{esc(c)}</th>' for i, c in enumerate(columns))
    body = "".join("<tr>" + "".join(f'<td class="{"num" if i in numeric else ""}">{c}</td>' for i, c in enumerate(r)) + "</tr>" for r in rows)
    return f'<div class="tbl-wrap"><table class="tbl"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def citation(c: dict) -> str:
    verified = badge("verified", "Verified against index", dot=False) if c.get("verified") else badge("failed", "UNVERIFIED", dot=False)
    return (f'<div class="cite"><div class="cite-head"><span class="clause">{esc(c.get("clause_id"))}</span>{verified}'
            f'<span class="meta">Page {esc(c.get("page"))}</span><span class="meta">{esc(c.get("chapter"))}</span></div>'
            f'<blockquote>{esc(c.get("quote"))}</blockquote>'
            f'<div class="src">{icon("file", 13)} Source document: {esc(c.get("document"))}</div></div>')


def outcome(kind: str, label: str, route: str, position: str, basis: str) -> str:
    """kind: ok | warn | bad | na — what the reader should conclude about the result."""
    cls = "" if kind == "ok" else kind
    return (f'<div class="outcome {cls}"><div class="k">{esc(label)}</div><div class="route">{esc(route)}</div>'
            f'<p><b>Position.</b> {esc(position)}</p><p>{esc(basis)}</p></div>')


def stepper(steps: list[tuple[str, str]]) -> str:
    """steps: (label, state) with state in done|active|fail|skip|''"""
    out = []
    for n, (label, state) in enumerate(steps, 1):
        mark = "✓" if state == "done" else "!" if state == "fail" else str(n)
        out.append(f'<div class="step {state}"><i>{mark}</i>{esc(label)}</div>')
    return '<div class="steps" role="list">' + "".join(out) + "</div>"


def timeline(items: list[dict]) -> str:
    """items: {t, title, detail, kind}"""
    lis = "".join(f'<li class="{esc(i.get("kind", ""))}"><span class="t">{esc(i["t"])}</span><b>{esc(i["title"])}</b>'
                  f'{(" · " + esc(i["detail"])) if i.get("detail") else ""}</li>' for i in items)
    return f'<ul class="tl">{lis}</ul>'


# --- charts (one look everywhere) ---
def _theme(ch: alt.Chart, height: int) -> alt.Chart:
    return (ch.properties(height=height, background="transparent")
            .configure_view(strokeWidth=0)
            .configure_axis(labelColor=TOKENS["ink2"], titleColor=TOKENS["muted"], labelFont="Inter, system-ui, sans-serif",
                            labelFontSize=12, titleFontSize=12, grid=False, domainColor=TOKENS["line_strong"], tickColor="transparent")
            .configure_axisY(labelLimit=220))


def bar_chart(data: dict, color: str = "teal", height: Optional[int] = None) -> alt.Chart:
    """Horizontal bars with value labels, from real counts only."""
    rows = [{"label": k, "count": v} for k, v in data.items()]
    h = height or max(60, 34 * len(rows))
    base = alt.Chart(alt.Data(values=rows)).encode(y=alt.Y("label:N", sort="-x", title=None),
                                                   x=alt.X("count:Q", title=None, axis=alt.Axis(tickMinStep=1, format="d")))
    bars = base.mark_bar(color=CHART[color], cornerRadiusEnd=3, size=16)
    text = base.mark_text(align="left", dx=6, color=TOKENS["ink"], fontSize=12, fontWeight=600).encode(text="count:Q")
    return _theme(alt.layer(bars, text), h)
