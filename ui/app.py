"""Streamlit client. Talks to the FastAPI backend only (ApiClient). Presentation only: no business logic, no invented data."""
from __future__ import annotations

import hashlib
import json
import os
import time

import streamlit as st

import components as ui
from api_client import ApiClient, ApiError
from style import CSS

TERMINAL = {"completed", "escalated", "failed"}
API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

st.set_page_config(page_title="Petition Triage", page_icon=":material/description:", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)
st.markdown("<style>.st-key-cta_new{margin-top:2.1rem}</style>", unsafe_allow_html=True)

NAV_STUDENT = [("New petition", "add_circle"), ("Track petition", "travel_explore")]
NAV_EXAMINER = [("Dashboard", "dashboard"), ("Review petition", "rule"), ("Run status", "manage_search"),
                ("Corpus & system", "database"), ("Evaluation", "fact_check"), ("Health & feedback", "monitor_heart")]
NAV_BY_VIEW = {"Student": NAV_STUDENT, "Examiner": NAV_EXAMINER}


@st.cache_resource
def _default_client() -> ApiClient:
    return ApiClient(API_BASE_URL)


def get_client() -> ApiClient:
    # Tests inject a client through session_state; production uses the HTTP client.
    return st.session_state.get("_api") or _default_client()


def goto(page: str, run_id: str | None = None) -> None:
    st.session_state["page"] = page
    if run_id:
        st.session_state["run_id"] = run_id
        for key in ("review_id", "track_id"):      # keyed inputs keep their own state, which would override the default
            st.session_state[key] = run_id
    st.rerun()


def html(s: str) -> None:
    st.markdown(s, unsafe_allow_html=True)


def api_down(e: ApiError) -> None:
    html(ui.alert("bad", "Backend unavailable", f"{e}. Check that the API container is running: docker compose ps"))


def fmt_ts(ts: str) -> str:
    return ts[:16].replace("T", " ") if ts else "—"


# ---------------------------------------------------------------- shell
def sidebar() -> str:
    st.session_state.setdefault("view", "Student")
    with st.sidebar:
        html(ui.brand())
        html('<div class="nav-label">View</div>')
        st.radio("View", list(NAV_BY_VIEW), key="view", horizontal=True, label_visibility="collapsed")
        st.caption("This switch is not a login: there is no authentication or access control in this system.")
        nav = NAV_BY_VIEW[st.session_state["view"]]
        page = st.session_state.get("page")
        if page not in [n[0] for n in nav]:
            page = st.session_state["page"] = nav[0][0]
        html('<div class="nav-label">Workspace</div>')
        for i, (label, icon_name) in enumerate(nav):
            active = label == page
            if st.button(label, icon=f":material/{icon_name}:", key=f"{'navactive' if active else 'nav'}_{i}", width="stretch") and not active:
                goto(label)
        rows = []
        try:
            ready, corpus = get_client().ready(), get_client().corpus()
            c = ready.get("checks", {})
            rows = [("API", ui.dot("ok") + "online"),
                    ("Corpus", ui.dot("ok" if corpus["ready"] else "warn") + ("ready" if corpus["ready"] else "not ready")),
                    ("LLM", ui.dot("ok" if c.get("llm") == "configured" else "warn") + ("configured" if c.get("llm") == "configured" else "not configured"))]
        except ApiError:
            rows = [("API", ui.dot("bad") + "unreachable")]
        html('<div class="side-status">' + "".join(f'<div class="row"><span>{ui.esc(k)}</span><span>{v}</span></div>' for k, v in rows) + "</div>")
        html('<div class="side-foot">Recommendations only. An examination officer decides every petition. Use synthetic data only.</div>')
    return page


# ---------------------------------------------------------------- dashboard
def page_dashboard() -> None:
    html(ui.page_header("Examiner dashboard", "Petition runs awaiting human review, system readiness and where cases get escalated.", "Dashboard", rule=False))
    try:
        data, corpus, ready = get_client().runs(15), get_client().corpus(), get_client().ready()
    except ApiError as e:
        return api_down(e)
    counts = data["counts"]
    total = sum(counts.values())
    html(ui.stat_strip([(total, "Total runs"), (counts.get("queued", 0) + counts.get("running", 0), "In progress"),
                        (counts.get("completed", 0), "Completed"), (counts.get("escalated", 0), "Escalated to a human", counts.get("escalated", 0) > 0),
                        (counts.get("failed", 0), "Failed", counts.get("failed", 0) > 0)]))

    html(ui.section("System readiness"))
    c = ready.get("checks", {})
    def ind(label, ok, detail):
        return f'<div class="row"><span>{ui.dot("ok" if ok else "warn")}{ui.esc(label)}</span><span class="mono">{ui.esc(detail)}</span></div>'
    items = [ind("Queue (Redis)", c.get("redis") == "ok", c.get("redis", "?")), ind("Database", c.get("database") == "ok", c.get("database", "?")),
             ind("Vector index", c.get("chroma") == "ok", c.get("chroma", "?")),
             ind("Corpus", corpus["ready"], f'{corpus["chunks_indexed"]} chunks · {corpus["documents_indexed"]} document(s)'),
             ind("LLM provider", c.get("llm") == "configured", c.get("llm", "?")), ind("Workers", c.get("workers", "0") not in ("0", "?"), c.get("workers", "?"))]
    html('<div class="panel side-status" style="margin:0">' + "".join(items) + "</div>")
    if c.get("llm") != "configured":
        html('<div style="height:12px"></div>' + ui.alert("warn", "No LLM provider configured",
             "Petitions are validated and queued, but every run escalates to a human with reason llm_unavailable. Real reasoning is unavailable until LLM_BASE_URL and LLM_MODEL are set."))

    html(ui.section("Recent runs", f"latest {len(data['runs'])}" if data["runs"] else ""))
    if not data["runs"]:
        html(ui.empty_state("No runs yet", "Submit a petition to see it processed here."))
    else:
        html('<div class="rr-head"><span>AI status</span><span>Type / human decision</span><span>Student</span><span>Created</span><span></span></div>')
        for i, r in enumerate(data["runs"]):
            with st.container(key=f"runrow_{i}"):
                c1, c2, c3, c4, c5 = st.columns([130, 110, 130, 110, 90], vertical_alignment="center")
                c1.markdown(ui.badge(r["status"]), unsafe_allow_html=True)
                human = ui.esc(r.get("examiner_decision") or "awaiting human decision" if r["status"] in TERMINAL else "")
                c2.markdown(f'<b>{ui.esc(r["petition_type"])}</b><br><span class="mono">{human}</span>', unsafe_allow_html=True)
                c3.markdown(f'{ui.esc(r["student_ref"])}<br><span class="mono">{ui.esc(r["run_id"])}</span>', unsafe_allow_html=True)
                c4.markdown(f'<span class="mono">{ui.esc(fmt_ts(r["created_at"]))}</span>', unsafe_allow_html=True)
                if c5.button("Review", key=f"open_{i}", width="stretch"):
                    goto("Review petition", r["run_id"])

    try:
        stt = get_client().stats()
    except ApiError:
        stt = None
    if stt and stt["runs_considered"]:
        html(ui.section("Outcomes", f'{stt["runs_considered"]} most recent runs'))
        a, b = st.columns(2)
        with a:
            html('<div class="panel"><h3>Runs by status</h3></div>')
            st.altair_chart(ui.bar_chart(stt["by_status"], "navy"), width="stretch")
        with b:
            html('<div class="panel"><h3>Escalations by reason</h3></div>')
            if stt["escalation_reasons"]:
                st.altair_chart(ui.bar_chart(stt["escalation_reasons"], "copper"), width="stretch")
            else:
                html(ui.empty_state("No escalations", "Nothing has been escalated in these runs."))
        lat, cost = stt["latency_seconds"], stt["cost"]
        html(ui.kv([("Latency p50 / p95", f'{ui.esc(lat["p50"] if lat["p50"] is not None else "—")} s / {ui.esc(lat["p95"] if lat["p95"] is not None else "—")} s'),
                    ("Estimated cost / 100 runs", ui.esc(f'${cost["usd_per_100_runs"]}') if cost["usd_per_100_runs"] is not None else "unknown (no price configured)")]))


# ---------------------------------------------------------------- supporting documents
def upload_widget(run_id: str) -> None:
    """Attach supporting documents to a petition. They are stored for the examiner only; no agent reads them."""
    html(ui.section("Supporting documents", "optional"))
    html('<p class="fd">PDF, PNG or JPEG, up to 2 MB each, at most 3 per petition. The file type is checked by content. '
         'Documents are stored for the human examiner; the AI agents do not read or verify them.</p>')
    files = st.file_uploader("Add documents", type=["pdf", "png", "jpg", "jpeg"], accept_multiple_files=True,
                             key=f"upload_{run_id}", label_visibility="collapsed")
    if st.button("Upload selected documents", key=f"upload_btn_{run_id}", disabled=not files):
        for f in files:
            try:
                res = get_client().upload_document(run_id, f.name, f.getvalue(), f.type or "application/octet-stream")
                html(ui.alert("ok", "Document stored", f'{res["filename"]} · {res["size"]} bytes · sha256 {res["sha256"][:12]}…'))
            except ApiError as e:
                html(ui.alert("bad", f"Not stored: {f.name}", str(e)))


# ---------------------------------------------------------------- submit
FIELD_MAP = {"student_ref": "student_ref", "program": "program", "admission_batch": "admission_batch", "course_code": "course_code",
             "semester": "semester", "petition_text": "petition_text", "classes_held": "classes_held", "classes_attended": "classes_attended"}


def ferr(field: str) -> None:
    msg = st.session_state.get("form_errors", {}).get(field)
    if msg:
        html(f'<div class="ferr">{ui.icon("x", 14)}{ui.esc(msg)}</div>')


def page_submit() -> None:
    html(ui.page_header("New petition", "Submit a synthetic student petition for triage. Nothing here is a university decision.", "Petitions"))
    html(ui.alert("info", "Synthetic data only", "Use student references like SYN-000123. Real student records must never be entered."))
    last = st.session_state.get("last_submission")
    if last:
        html(ui.alert("ok", "Petition accepted", "It is queued and will be processed asynchronously.") +
             ui.kv([("Run ID", f'<span class="mono">{ui.esc(last["run_id"])}</span>')]))
        upload_widget(last["run_id"])
        if st.button("Track this petition", icon=":material/arrow_forward:", type="primary", key="inspect_run"):
            goto("Track petition", last["run_id"])
    errs = st.session_state.get("form_errors")
    if errs:
        html(ui.alert("bad", "The petition was rejected and quarantined", "No run was started. Fix the highlighted fields and submit again."))
    with st.form("petition", border=True):
        html('<div class="fs">Student and course</div><p class="fd">Who the petition is about and which course it concerns.</p>')
        c1, c2 = st.columns(2)
        with c1:
            student_ref = st.text_input("Student reference", "SYN-000123", help="Format SYN-000000 (synthetic)")
            ferr("student_ref")
        with c2:
            program = st.text_input("Programme", "Computer Science and Engineering")
            ferr("program")
        c3, c4, c5 = st.columns(3)
        with c3:
            batch = st.text_input("Admission batch", "2025-26", help="e.g. 2025-26")
            ferr("admission_batch")
        with c4:
            course = st.text_input("Course code", "CS101")
            ferr("course_code")
        with c5:
            semester = st.number_input("Semester", 1, 8, 3)
            ferr("semester")
        html('<div class="fs">Petition</div><p class="fd">The type decides which regulations apply. Only attendance is supported today; other types are escalated.</p>')
        ptype = st.selectbox("Petition type", ["attendance", "re-evaluation", "re-registration", "medical-leave", "grade-grievance"])
        html('<div class="fs">Attendance</div><p class="fd">Classes held and attended in this course. Use 0 held if not applicable.</p>')
        c6, c7, c8 = st.columns(3)
        with c6:
            held = st.number_input("Classes held", 0, 1000, 50)
            ferr("classes_held")
        with c7:
            attended = st.number_input("Classes attended", 0, 1000, 40)
            ferr("classes_attended")
        with c8:
            pct = round(100 * attended / held, 1) if held else None
            st.text_input("Attendance %", f"{pct}" if pct is not None else "n/a", disabled=True)
            ferr("attendance_percentage")
        html('<div class="fs">Reason and documentation</div><p class="fd">Condonation can depend on valid grounds and supporting documents.</p>')
        c9, c10 = st.columns(2)
        reason = c9.selectbox("Reason", ["medical", "personal", "sports-cultural", "other"])
        docs = c10.selectbox("Medical documentation", ["certificate", "hospital-record", "none"])
        html('<div class="fs">Statement</div>')
        text = st.text_area("Petition text", "I was hospitalised for three weeks and request that my attendance shortage be considered.",
                            height=120, help="20–2000 characters. Treated as data, never as instructions.")
        ferr("petition_text")
        ferr("(request)")
        submitted = st.form_submit_button("Submit petition", type="primary", icon=":material/send:")
    if not submitted:
        return
    payload = {"student_ref": student_ref, "program": program, "admission_batch": batch, "petition_type": ptype, "course_code": course,
               "semester": int(semester), "reason_category": reason, "medical_documentation": docs, "petition_text": text}
    if held:
        payload.update(classes_held=int(held), classes_attended=int(attended), attendance_percentage=round(100 * attended / held, 1))
    fp = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    if last and last.get("fp") == fp:                      # duplicate-submission guard: identical payload already accepted
        html(ui.alert("warn", "Identical petition already submitted", f'It was accepted as {last["run_id"]}. Change a field to submit a new one.'))
        return
    try:
        with st.spinner("Submitting petition…"):
            res = get_client().submit(payload)
    except ApiError as e:
        if e.status == 422:
            st.session_state["form_errors"] = {FIELD_MAP.get(x["field"], x["field"]): x["message"] for x in e.body["errors"]}
            st.rerun()
        return api_down(e)
    st.session_state["form_errors"] = {}
    st.session_state["last_submission"] = {"run_id": res["run_id"], "fp": fp}
    st.session_state["run_id"] = res["run_id"]
    st.rerun()


# ---------------------------------------------------------------- run status
ROUTE_LABEL = {"grant-under-provision": "Grant under a provision", "refer-to-committee": "Refer to committee / authority", "reject": "Reject, citing a clause"}
STEPS = [("Queued", None), ("Triage", "triage"), ("Research", "research"), ("Verifier", "verifier"), ("Result", None)]


def progress_steps(r: dict) -> str:
    """Pipeline stepper derived from run_events (it only reads what the backend recorded)."""
    ev = r["events"]
    started = {e["detail"].get("agent") for e in ev if e["event"] == "agent_start"}
    ended = {e["detail"].get("agent"): e["detail"].get("ok") for e in ev if e["event"] == "agent_end"}
    terminal = r["status"] in TERMINAL
    out = []
    for label, agent in STEPS:
        if label == "Queued":
            state = "done" if r["status"] != "queued" else "active"
        elif label == "Result":
            state = ("fail" if r["status"] == "failed" else "done") if terminal else ""
        elif agent in ended:
            state = "done" if ended[agent] else "fail"
        elif agent in started:
            state = "active"
        else:
            state = "skip" if terminal else ""
        out.append((label, state))
    return ui.stepper(out)


def timeline_items(r: dict) -> list[dict]:
    ev = r["events"]
    if not ev:
        return []
    from datetime import datetime
    t0 = datetime.fromisoformat(ev[0]["ts"]).timestamp()
    out = []
    for e in ev:
        d, n = e.get("detail") or {}, e["event"]
        t = f'+{datetime.fromisoformat(e["ts"]).timestamp() - t0:.1f}s'
        if n == "agent_start":
            out.append({"t": t, "title": f'{str(d.get("agent", "")).capitalize()} started'})
        elif n == "agent_end":
            out.append({"t": t, "title": f'{str(d.get("agent", "")).capitalize()} {"finished" if d.get("ok") else "failed"}',
                        "detail": "" if d.get("ok") else d.get("escalation") or d.get("error", ""), "kind": "hl" if d.get("ok") else "bad"})
        elif n == "tool_call":
            res = d.get("results") or []
            out.append({"t": t, "title": f'Retrieval · {d.get("tool")}', "detail": (f'{len(res)} passage(s)' if d.get("ok") else d.get("error", "failed")),
                        "kind": "" if d.get("ok") else "bad"})
        elif n == "handoff":
            out.append({"t": t, "title": f'Hand-off {d.get("from_agent")} → {d.get("to_agent")}'})
        elif n in ("llm_retry", "llm_fallback", "llm_skipped"):
            out.append({"t": t, "title": n.replace("_", " ").capitalize(), "detail": f'{d.get("provider", "")} {d.get("kind", d.get("reason", ""))}'.strip(), "kind": "warn"})
        elif n == "guardrail":
            out.append({"t": t, "title": f'Guardrail ({d.get("stage")})', "detail": "blocked", "kind": "warn"})
        elif n == "verification":
            out.append({"t": t, "title": "Citation verification", "detail": "passed" if d.get("ok") else "failed", "kind": "hl" if d.get("ok") else "warn"})
        elif n == "escalation":
            out.append({"t": t, "title": "Escalated to a human", "detail": d.get("reason") or "", "kind": "warn"})
        elif n in ("queued", "running"):
            out.append({"t": t, "title": n.capitalize()})
        elif n in TERMINAL:
            out.append({"t": t, "title": f"Run {n}", "kind": "bad" if n == "failed" else "hl" if n == "completed" else "warn"})
    return out


def render_outcome(r: dict) -> None:
    res, status = r.get("result"), r["status"]
    if status == "failed":
        return html(ui.alert("bad", "Run failed — no result", r.get("error") or "The run ended in an error and produced no recommendation."))
    if status in ("queued", "running"):
        return html(ui.alert("info", "Processing", "Triage, research and verification are running. This page updates automatically."))
    if not res:
        return
    if res.get("mode") == "placeholder":
        return html(ui.alert("na", "Placeholder result — not an AI recommendation",
                             "No regulations were retrieved and no agent or model was used. This is not an eligibility position."))
    models = res.get("llm_models") or []
    if any(w in m.lower() for m in models for w in ("stub", "scripted", "fake", "mock")):
        html(ui.alert("na", "Produced by a stub / scripted model — not real AI reasoning",
                      "Model: " + ", ".join(models) + ". The retrieval and citation verification are real, but the recommendation text was not written by a real LLM."))
    esc = res.get("escalation") or {}
    route = ROUTE_LABEL.get(res.get("route"), "No route")
    if res.get("position") == "NO_DETERMINATION":
        html(ui.outcome("na", "No determination", "A human must decide", "No determination was made.", res.get("basis") or ""))
    elif esc.get("required"):
        html(ui.outcome("warn", "Recommendation · escalated for human decision", route, res.get("position", ""), res.get("basis", "")))
    else:
        html(ui.outcome("ok", "Recommendation · not a final decision", route, res.get("position", ""), res.get("basis", "")))
    if esc.get("required"):
        html(ui.alert("warn", f'Escalated to a human — {esc.get("reason")}', esc.get("detail", "") + " No final decision has been made."))
    else:
        html(ui.alert("info", "Recommendation only", "No final decision has been made. An examination officer decides every petition."))
    html(ui.alert("warn", "Human review is required", "An examination officer must review this petition and record the decision. "
                  "Nothing on this page is a university decision."))
    qs = res.get("open_questions") or []
    if qs:
        with st.expander(f"Unresolved interpretations behind this recommendation ({len(qs)}) — NOT verified"):
            for q in qs:
                st.markdown(f'**{q["id"]} · {q["topic"]}** — {q["text"]}')
    cl = res.get("human_review_checklist") or []
    if cl:
        with st.expander("Checklist for the human reviewer"):
            for item in cl:
                st.markdown(f"- {item}")


def render_evidence(res: dict) -> None:
    cites = res.get("citations") or []
    html(ui.section("Evidence", f"{len(cites)} verified citation(s)"))
    if not cites:
        reviewed = ", ".join(f'{e["clause_id"]} (p.{e["page"]})' for e in res.get("evidence_reviewed", []))
        html(ui.empty_state("No verified citations", ("Passages reviewed but not cited: " + reviewed) if reviewed else "No evidence was retrieved."))
    for c in cites:
        html(ui.citation(c))


def render_run(r: dict) -> None:
    html(f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:14px">{ui.badge(r["status"])}'
         f'<span class="mono">{ui.esc(r["run_id"])}</span><span>·</span><b>{ui.esc(r["petition_type"])}</b><span>{ui.esc(r["student_ref"])}</span></div>')
    html(progress_steps(r))
    left, right = st.columns([3, 2], gap="large")
    with left:
        render_outcome(r)
        res = r.get("result") or {}
        if res.get("mode") == "agents":
            render_evidence(res)
            pv, stt, cst = res.get("prompt_versions") or {}, res.get("agent_stats") or {}, res.get("cost") or {}
            rows = [("Model", ui.esc(", ".join(res.get("llm_models") or []) or "—")), ("Prompts", ui.esc(", ".join(pv.values()) or "—")), ("Tool calls", ui.esc(stt.get("tool_calls", "—"))),
                    ("Verification attempts", ui.esc(stt.get("verify_attempts", "—")))]
            if cst.get("llm_calls"):
                usd = cst.get("estimated_cost_usd")
                rows.append(("Tokens", ui.esc(f'{cst["prompt_tokens"]} prompt + {cst["completion_tokens"]} completion ({cst["token_source"]})')))
                rows.append(("Estimated cost", ui.esc(f"${usd:.4f}") if usd is not None else "unknown (no price configured)"))
            html(ui.section("Run details") + ui.kv(rows))
    with right:
        html(ui.section("Timeline"))
        items = timeline_items(r)
        html(ui.timeline(items) if items else ui.empty_state("No events yet"))


def render_run_details(run_id: str, r: dict) -> None:
    html(ui.section("Diagnostics"))
    tab_trace, tab_ret, tab_events, tab_fb = st.tabs(["Run trace", "Retrieval history", "Events", "Feedback"])
    try:
        t = get_client().trace(run_id)
    except ApiError as e:
        t = None
        tab_trace.warning(f"Trace unavailable: {e}")
    if t:
        with tab_trace:
            st.caption(f'{t["total_seconds"]} s end-to-end · {t["event_count"]} events · LLM retries: {t["retry_count"]} · correlation id: {t.get("correlation_id")}')
            rows = [[ui.esc(a), ui.esc(v["runs"]), ui.esc(v["failures"]), ui.esc(v["seconds"]), ui.esc(v["llm_calls"]), ui.esc(v["tool_calls"])] for a, v in t["agents"].items()]
            if rows:
                html(ui.table(["Agent", "Runs", "Failures", "Seconds", "LLM calls", "Tool calls"], rows, {1, 2, 3, 4, 5}))
            if t["llm_calls"]:
                html(ui.section("LLM calls"))
                html(ui.table(["At", "Agent", "OK", "Provider", "Latency", "Tokens (p/c)", "Error"],
                              [[ui.esc(c.get("at_s")), ui.esc(c.get("agent")), ui.esc("yes" if c.get("ok") else "no"), ui.esc(c.get("provider") or "—"),
                                ui.esc(c.get("latency_s")), ui.esc(f'{c.get("prompt_tokens")}/{c.get("completion_tokens")}'), ui.esc(c.get("error") or "")] for c in t["llm_calls"]]))
            for x in t["retries_and_fallbacks"]:
                st.caption(f'{x["at_s"]}s · {x["event"]} · provider={x.get("provider")} kind={x.get("kind")}')
        with tab_ret:
            if not t["retrieval_history"]:
                html(ui.empty_state("No retrieval was performed for this run"))
            for h in t["retrieval_history"]:
                found = ", ".join(f'{x["clause_id"]} (p.{x["page"]}, {x["score"]})' for x in h["results"]) or (h.get("error") or "no results")
                html(f'<div class="panel" style="margin-bottom:8px">{ui.badge("completed" if h["ok"] else "failed", "ok" if h["ok"] else "failed", dot=False)} '
                     f'<b>{ui.esc(h["tool"])}</b> <span class="mono">{ui.esc(h.get("args"))}</span><br>{ui.esc(found)}</div>')
    with tab_events:
        for e in r["events"]:
            d = e.get("detail") or {}
            st.markdown(f'`{e["ts"][11:23]}` **{e["event"]}** {d.get("tool") or d.get("agent") or d.get("reason") or ""}')
    with tab_fb:
        with st.form(f"fb-{run_id}"):
            rating = st.slider("How useful was this recommendation?", 1, 5, 4)
            agrees = st.radio("Do you agree with the recommended route?", ["No answer", "Yes", "No"], horizontal=True)
            comment = st.text_input("Comment (optional, no personal data)", max_chars=500)
            if st.form_submit_button("Send feedback"):
                try:
                    get_client().send_feedback(run_id, rating, {"Yes": True, "No": False}.get(agrees), comment)
                    html(ui.alert("ok", "Thank you", "Feedback stored."))
                except ApiError as e:
                    html(ui.alert("bad", "Feedback not stored", str(e)))


def page_run() -> None:
    html(ui.page_header("Run status", "Live progress, outcome, evidence and diagnostics for one run.", "Runs"))
    run_id = st.text_input("Run ID", st.session_state.get("run_id", ""), placeholder="run_…")
    if not run_id:
        return html(ui.empty_state("No run selected", "Enter a run ID, open one from the dashboard, or submit a new petition."))
    holder = st.empty()
    r = None
    for _ in range(40):
        try:
            r = get_client().run(run_id)
        except ApiError as e:
            return api_down(e) if e.status is None else html(ui.alert("bad", "Run not found" if e.status == 404 else "Error", str(e)))
        with holder.container():
            render_run(r)
        if r["status"] in TERMINAL:
            break
        time.sleep(1.5)
    else:
        return html(ui.alert("info", "Still processing", "Reload to keep polling."))
    render_run_details(run_id, r)


# ---------------------------------------------------------------- student: track a petition
DECISION_LABEL = {"accept-petition": "Petition accepted by the examiner", "reject-petition": "Petition rejected by the examiner",
                  "request-more-information": "The examiner asked for more information"}


DECISION_CHOICE = {"accept-petition": "Accept the petition", "reject-petition": "Reject the petition",
                   "request-more-information": "Request more information"}


def render_human_decision(r: dict) -> None:
    ds = r.get("examiner_decisions") or []
    if not ds:
        return html(ui.alert("info", "No human decision recorded yet", "An examiner has not recorded a decision for this petition."))
    d = ds[-1]
    html(ui.alert("ok", DECISION_LABEL.get(d["decision"], d["decision"]),
                  f'Recorded {fmt_ts(d["ts"])} by {d["examiner_label"]} (self-declared; no login). Examiner\'s note: {d["note"]}'))


def page_track() -> None:
    html(ui.page_header("Track petition", "Status, the system's recommendation, its evidence and whether a human has decided.", "Petitions"))
    run_id = st.text_input("Petition (run) ID", st.session_state.get("run_id", ""), placeholder="run_…", key="track_id").strip()
    if not run_id:
        return html(ui.empty_state("No petition selected", "Enter the run ID you received when you submitted the petition."))
    holder = st.empty()
    r = None
    for _ in range(40):
        try:
            r = get_client().run(run_id)
        except ApiError as e:
            return api_down(e) if e.status is None else html(ui.alert("bad", "Petition not found" if e.status == 404 else "Error", str(e)))
        with holder.container():
            html(f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:14px">{ui.badge(r["status"])}'
                 f'<span class="mono">{ui.esc(r["run_id"])}</span><span>·</span><b>{ui.esc(r["petition_type"])}</b></div>')
            html(progress_steps(r))
            render_outcome(r)
        if r["status"] in TERMINAL:
            break
        time.sleep(1.5)
    else:
        return html(ui.alert("info", "Still processing", "Reload to keep polling."))
    if r.get("result") and r["result"].get("mode") == "agents":
        render_evidence(r["result"])
    html(ui.section("Human decision"))
    render_human_decision(r)
    docs = r.get("documents") or []
    if docs:
        html(ui.section("Your documents", f"{len(docs)} stored"))
        html(ui.table(["File", "Type", "Size (bytes)"], [[ui.esc(d["filename"]), ui.esc(d["content_type"]), ui.esc(d["size"])] for d in docs], {2}))
    upload_widget(run_id)


# ---------------------------------------------------------------- examiner: review a petition
def page_review() -> None:
    html(ui.page_header("Review petition", "Inspect the petition, supporting documents and the AI recommendation, then record your own decision.", "Examiner"))
    html(ui.alert("info", "Your decision is separate from the AI recommendation",
                  "The AI output is a recommendation only. What you record below is stored as a distinct human decision. "
                  "Your name is self-declared: this system has no authentication."))
    run_id = st.text_input("Run ID", st.session_state.get("run_id", ""), placeholder="run_…", key="review_id").strip()
    if not run_id:
        return html(ui.empty_state("No petition selected", "Open one from the dashboard, or enter a run ID."))
    try:
        r = get_client().run(run_id)
    except ApiError as e:
        return api_down(e) if e.status is None else html(ui.alert("bad", "Run not found" if e.status == 404 else "Error", str(e)))
    html(f'<div style="display:flex;align-items:center;gap:12px;margin:8px 0 14px">{ui.badge(r["status"])}'
         f'<span class="mono">{ui.esc(r["run_id"])}</span><span>·</span><b>{ui.esc(r["petition_type"])}</b><span>{ui.esc(r["student_ref"])}</span></div>')
    p = r.get("petition") or {}
    html(ui.section("Petition as submitted", "synthetic data"))
    if p:
        held = f'{p.get("classes_attended")} / {p.get("classes_held")}' if p.get("classes_held") else "—"
        html(ui.kv([("Programme · batch", ui.esc(f'{p.get("program")} · {p.get("admission_batch")}')),
                    ("Course · semester", ui.esc(f'{p.get("course_code")} · {p.get("semester")}')),
                    ("Attendance", ui.esc(f'{p.get("attendance_percentage", "—")} % (attended/held: {held})')),
                    ("Reason · documentation", ui.esc(f'{p.get("reason_category")} · {p.get("medical_documentation")} (declared by the student; not verified)')),
                    ("Statement", ui.esc(p.get("petition_text", "")))]))
    docs = r.get("documents") or []
    html(ui.section("Supporting documents", f"{len(docs)} attached"))
    if not docs:
        html(ui.empty_state("No documents attached", "The student has not uploaded any supporting document."))
    for d in docs:
        try:
            data = get_client().download_document(run_id, d["id"])
            st.download_button(f'{d["filename"]} · {d["size"]} bytes · sha256 {d["sha256"][:10]}…', data, file_name=d["filename"],
                               mime=d["content_type"], key=f'dl_{d["id"]}')
        except ApiError as e:
            st.caption(f'{d["filename"]}: unavailable ({e})')
    html(ui.section("AI recommendation"))
    render_outcome(r)
    if r.get("result") and r["result"].get("mode") == "agents":
        render_evidence(r["result"])
        tri = r["result"].get("triage") or {}
        if tri:
            html(ui.kv([("Triage confidence", ui.esc(tri.get("confidence", "—"))), ("Triage summary", ui.esc(tri.get("summary", ""))),
                        ("Triage flags", ui.esc("; ".join(tri.get("flags") or []) or "none"))]))
    html(ui.section("Human decision"))
    ds = r.get("examiner_decisions") or []
    if ds:
        html(ui.table(["When", "Examiner (self-declared)", "Decision", "Note", "AI route at that time"],
                      [[ui.esc(fmt_ts(d["ts"])), ui.esc(d["examiner_label"]), ui.esc(d["decision"]), ui.esc(d["note"]),
                        ui.esc((d.get("ai_snapshot") or {}).get("route") or "—")] for d in ds]))
    if r["status"] not in TERMINAL:
        return html(ui.alert("info", "AI pipeline still running", "You can record a decision once the recommendation is ready. Reload to refresh."))
    with st.form(f"examiner-{run_id}"):
        label = st.text_input("Your name or initials (self-declared)", st.session_state.get("examiner_label", ""), max_chars=64)
        decision = st.radio("Your decision (no default: you must choose)", list(DECISION_CHOICE), index=None,
                            format_func=lambda k: DECISION_CHOICE[k])
        note = st.text_area("Your reasoning (required, 10–1000 characters)", height=110, max_chars=1000)
        if st.form_submit_button("Record my decision", type="primary", icon=":material/gavel:"):
            st.session_state["examiner_label"] = label
            if decision is None:
                return html(ui.alert("bad", "Choose a decision", "Select accept, reject or request more information."))
            try:
                get_client().examiner_decision(run_id, decision, note, label)
                html(ui.alert("ok", "Decision recorded", "Stored as a human decision, separate from the AI recommendation."))
                st.rerun()
            except ApiError as e:
                html(ui.alert("bad", "Decision not recorded", str(e)))


# ---------------------------------------------------------------- corpus & system
def page_corpus() -> None:
    html(ui.page_header("Corpus & system", "Which regulations are indexed, how fresh they are, and whether retrieval can be trusted.", "Knowledge base"))
    try:
        c = get_client().corpus()
    except ApiError as e:
        return api_down(e)
    if c["ready"]:
        html(ui.alert("ok", "Corpus ready", c["message"]))
    else:
        html(ui.alert("warn" if c["last_attempt_status"] is None else "bad", "Corpus not ready", c["message"]))
    html(ui.stat_strip([(c["documents_indexed"], "Documents indexed"), (c["chunks_indexed"], "Chunks"),
                        ("yes" if c["chroma_reachable"] else "no", "Vector store reachable"), ((c["last_ingest_at"] or "")[:10] or "never", "Last successful ingestion" + (f' ({c["last_ingest_at"][11:16]} UTC)' if c["last_ingest_at"] else ""))]))
    html(ui.section("Index"))
    html(ui.kv([("Source files", ui.esc(", ".join(c["sources_present"]) or "none found")), ("Embedding config", f'<span class="mono">{ui.esc(c["embedding_tag"] or "—")}</span>'),
                ("Last attempt", ui.esc(f'{c["last_attempt_status"] or "—"} · {fmt_ts(c["last_attempt_at"] or "")}'))]))
    dc = c["difficult_case"]
    html(ui.section("Assignment difficult case") + ui.alert("warn", f'Attendance condonation (medical): {dc["status"]}', dc["note"]))
    if c["verified_passages"]:
        html(ui.section("Verified-passage check", "each quote re-checked against the indexed text at ingestion"))
        html(ui.table(["Passage", "Status"], [[f'<span class="mono">{ui.esc(k)}</span>', ui.badge("completed" if v else "failed", "found" if v else "MISSING", dot=False)] for k, v in c["verified_passages"].items()]))
    for w in c["warnings"][:10]:
        st.caption("Warning: " + w)
    for e in c["errors"]:
        html(ui.alert("bad", "Ingestion error", e))


# ---------------------------------------------------------------- evaluation
def page_evaluation() -> None:
    html(ui.page_header("Evaluation", "Reproducible evaluation reports. Scripted-model runs test the safety machinery, not an LLM.", "Quality"))
    try:
        ev = get_client().evaluation()
    except ApiError as e:
        return api_down(e)
    if not ev["reports"]:
        html(ui.empty_state("No evaluation report found", "Run: python -m triage.evaluation.run --mode scripted"))
    for rep in ev["reports"]:
        meta, m = rep["meta"], rep["metrics"]
        scripted = meta["mode"] == "scripted"
        html(ui.section(rep["file"], f'{meta["scenario_count"]} scenarios · {meta["generated_at"][:16].replace("T", " ")}') +
             f'<div style="margin-bottom:12px">{ui.badge("escalated" if scripted else "completed", "Scripted model" if scripted else "Real LLM", dot=False)} '
             f'<span class="mono">model: {ui.esc(meta["model"])}</span></div>' +
             ui.alert("na" if scripted else "info", "How to read these numbers", meta["interpretation"]))
        rows = []
        for k, v in m.items():
            val = ui.esc(f'{v["value"]:.3f}') if v["value"] is not None else '<span style="color:var(--muted)">Unavailable</span>'
            rows.append([ui.esc(k.replace("_", " ").capitalize()), val, ui.esc(v["n"])])
        html(ui.table(["Metric", "Value", "Scenarios measured (n)"], rows, {1, 2}))
        j = rep.get("llm_judge") or {}
        html('<p class="fd" style="margin-top:8px">' + ("LLM-judge scores are in the full report." if j.get("enabled") else "LLM-judge scores: unavailable (needs a real LLM).") + "</p>")
        if rep.get("by_category"):
            html(ui.section("Scenario outcomes by category"))
            html(ui.table(["Category", "Scenarios", "Task success", "Escalation accuracy"],
                          [[ui.esc(k.replace("_", " ")), ui.esc(v["n"]), ui.esc(v["task_success"]), ui.esc(v["escalation_accuracy"])] for k, v in rep["by_category"].items()], {1, 2, 3}))
    exp = ev.get("experiment")
    if exp:
        html(ui.section("Experiment: derived second retrieval query", "retrieval-level ablation; does not measure an LLM"))
        html(ui.table(["Setting", "Queries", "A: condonation found", "B: condonation found", "A: both gold", "B: both gold"],
                      [[ui.esc(k), ui.esc(v["n_queries"]), ui.esc(v["A_condonation_found"]), ui.esc(v["B_condonation_found"]), ui.esc(v["A_both_found"]), ui.esc(v["B_both_found"])]
                       for k, v in exp["summary"].items()], {1, 2, 3, 4, 5}))


# ---------------------------------------------------------------- health & feedback
def page_health() -> None:
    html(ui.page_header("Health & feedback", "Dependency status, usage cost and what reviewers think of the recommendations.", "Operations"))
    try:
        ready, fb, stt, runs = get_client().ready(), get_client().feedback(), get_client().stats(), get_client().runs(30)
    except ApiError as e:
        return api_down(e)
    c = ready.get("checks", {})
    def row(name, ok, detail):
        return [f'{ui.dot("ok" if ok else "warn")}{ui.esc(name)}', f'<span class="mono">{ui.esc(detail)}</span>']
    html(ui.section("Services"))
    html(ui.table(["Service", "Status"], [row("Queue (Redis)", c.get("redis") == "ok", c.get("redis")), row("Database", c.get("database") == "ok", c.get("database")),
                                          row("Vector index (Chroma)", c.get("chroma") == "ok", c.get("chroma")), row("Workers", c.get("workers", "0") not in ("0", "?"), c.get("workers")),
                                          row("LLM provider", c.get("llm") == "configured", c.get("llm")), row("LLM circuit breaker", c.get("llm_breaker") == "closed", c.get("llm_breaker"))]))
    if c.get("degraded", "none") != "none":
        html('<div style="height:12px"></div>' + ui.alert("warn", "Degraded", c["degraded"]))
    t, cost = stt["tokens"], stt["cost"]
    html(ui.section("Usage and cost", f'{stt["runs_considered"]} recent runs'))
    html(ui.kv([("Tokens", ui.esc(f'{t["prompt"]} prompt + {t["completion"]} completion ({t["runs_with_estimated_tokens"]} run(s) estimated)')),
                ("Estimated cost / 100 runs", ui.esc(f'${cost["usd_per_100_runs"]}') if cost["usd_per_100_runs"] is not None else "unknown — no price configured")]))
    s = fb["stats"]
    html(ui.section("Feedback"))
    html(ui.stat_strip([(s["count"], "Entries"), (s["mean_rating"] if s["mean_rating"] is not None else "—", "Mean rating (1–5)"),
                        (f'{round(100 * s["satisfaction_rate"])} %' if s["satisfaction_rate"] is not None else "—", "Satisfied (4–5)"),
                        (f'{round(100 * s["agreement_rate"])} %' if s["agreement_rate"] is not None else "—", "Agree with route")]))
    if s["count"]:
        st.altair_chart(ui.bar_chart({f"{k} star": v for k, v in s["distribution"].items() if v}, "teal"), width="stretch")
    else:
        html('<div style="height:12px"></div>' + ui.empty_state("No feedback yet", "Ratings appear here once reviewers submit them."))
    finished = [r for r in runs["runs"] if r["status"] in TERMINAL]
    html(ui.section("Give feedback"))
    if not finished:
        return html(ui.empty_state("No finished runs", "Feedback can be given once a run has finished."))
    with st.form("health-feedback"):
        pick = st.selectbox("Run", [r["run_id"] for r in finished], format_func=lambda i: next(f'{x["run_id"]} · {x["petition_type"]} · {x["status"]}' for x in finished if x["run_id"] == i))
        rating = st.slider("How useful was the recommendation?", 1, 5, 4)
        agrees = st.radio("Do you agree with the recommended route?", ["No answer", "Yes", "No"], horizontal=True)
        comment = st.text_input("Comment (optional, no personal data)", max_chars=500)
        if st.form_submit_button("Send feedback", type="primary"):
            try:
                get_client().send_feedback(pick, rating, {"Yes": True, "No": False}.get(agrees), comment)
                html(ui.alert("ok", "Thank you", "Feedback stored."))
            except ApiError as e:
                html(ui.alert("bad", "Feedback not stored", str(e)))
    if fb["recent"]:
        html(ui.section("Recent feedback"))
        html(ui.table(["Run", "Rating", "Agrees", "Comment"], [[f'<span class="mono">{ui.esc(x["run_id"])}</span>', ui.esc(x["rating"]),
                      ui.esc({1: "yes", 0: "no"}.get(x["agrees"], "—")), ui.esc(x["comment"] or "")] for x in fb["recent"][:5]], {1}))


PAGES = {"Dashboard": page_dashboard, "New petition": page_submit, "Track petition": page_track, "Review petition": page_review,
         "Run status": page_run, "Corpus & system": page_corpus, "Evaluation": page_evaluation, "Health & feedback": page_health}

PAGES[sidebar()]()
