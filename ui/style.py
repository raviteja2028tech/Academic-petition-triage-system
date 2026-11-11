"""Design system: tokens + CSS. One place defines colour, type, spacing, radius and component styles.

Palette: warm paper background, midnight-blue ink, restrained teal for "verified / healthy", copper for the one primary action.
Type: Inter (falls back to the system UI font when offline) for UI, a serif stack for page titles.
Scale: spacing 4/8/12/16/24/32/48 px; radii 6/10; type 12/13/14/16/20/28.
"""

TOKENS = {
    "bg": "#FAF8F4", "surface": "#FFFFFF", "sunken": "#F3EFE6", "ink": "#0B1B33", "ink2": "#34445C", "muted": "#5F6E84",
    "line": "#E6E1D6", "line_strong": "#D3CCBC", "teal": "#0F766E", "teal_bg": "#E4F3F0", "accent": "#B8481F",
    "accent_hover": "#9A3A15", "ok": "#166534", "ok_bg": "#E7F4EA", "warn": "#8A4B08", "warn_bg": "#FDF1DC",
    "bad": "#9B1C1C", "bad_bg": "#FCEBEB", "info": "#1E3A8A", "info_bg": "#E8EEFB", "neutral_bg": "#EEEAE1",
}
# chart colours (same family as the UI; used by every chart)
CHART = {"teal": TOKENS["teal"], "copper": TOKENS["accent"], "navy": TOKENS["ink"], "sand": "#CFC6B2", "red": "#B91C1C"}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
:root{
  --bg:#FAF8F4; --surface:#FFFFFF; --sunken:#F3EFE6; --ink:#0B1B33; --ink2:#34445C; --muted:#5F6E84;
  --line:#E6E1D6; --line2:#D3CCBC; --teal:#0F766E; --teal-bg:#E4F3F0; --accent:#B8481F; --accent-h:#9A3A15;
  --ok:#166534; --ok-bg:#E7F4EA; --warn:#8A4B08; --warn-bg:#FDF1DC; --bad:#9B1C1C; --bad-bg:#FCEBEB;
  --info:#1E3A8A; --info-bg:#E8EEFB; --neutral-bg:#EEEAE1;
  --sans:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  --serif:"Source Serif 4","Iowan Old Style",Georgia,"Times New Roman",serif;
  --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  --r1:6px; --r2:10px; --shadow:0 1px 2px rgba(11,27,51,.05);
}
html,body,.stApp,[data-testid="stAppViewContainer"]{background:var(--bg)!important;color:var(--ink);font-family:var(--sans);font-size:14px;line-height:1.5}
.stApp *{font-family:var(--sans)}
[data-testid="stIconMaterial"],.material-symbols-rounded{font-family:"Material Symbols Rounded"!important;font-weight:400;letter-spacing:normal;text-transform:none}
.stApp code,.mono{font-family:var(--mono)!important}
[data-testid="stHeader"]{background:transparent;height:0}
[data-testid="stToolbar"],.stAppDeployButton,[data-testid="stDecoration"],#MainMenu,footer{display:none!important}
.block-container{padding:2rem 2.5rem 3rem!important;max-width:1180px}
h1,h2,h3,h4{color:var(--ink);letter-spacing:-.01em;font-weight:600}
*:focus-visible{outline:2px solid var(--teal)!important;outline-offset:2px}
a{color:var(--teal)}

/* ---------- sidebar ---------- */
[data-testid="stSidebar"]{background:var(--sunken);border-right:1px solid var(--line);min-width:248px!important}
[data-testid="stSidebar"] .block-container,[data-testid="stSidebarContent"]{padding-top:1.25rem}
[data-testid="stSidebarHeader"],[data-testid="stSidebarCollapseButton"]{display:none}
.brand{display:flex;align-items:center;gap:12px;padding:4px 8px 20px}
.brand-mark{width:34px;height:34px;border-radius:9px;background:var(--ink);display:grid;place-items:center;flex:none}
.brand-name{font-weight:650;font-size:15px;color:var(--ink);line-height:1.15}
.brand-sub{font-size:11.5px;color:var(--muted);letter-spacing:.02em}
.nav-label{font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);padding:6px 10px}
[data-testid="stSidebar"] .stButton{margin:0 0 2px}
[data-testid="stSidebar"] .stButton button>div,[data-testid="stSidebar"] .stButton button [data-testid="stMarkdownContainer"]{justify-content:flex-start!important;text-align:left!important;width:100%}
[data-testid="stSidebar"] .stButton button{display:flex;justify-content:flex-start}
div[data-baseweb="select"] div{background-color:var(--surface)!important}
[data-testid="stSidebar"] .stButton>button{width:100%;justify-content:flex-start;gap:10px;background:transparent;border:1px solid transparent;
  color:var(--ink2);font-weight:500;font-size:14px;padding:.5rem .7rem;border-radius:var(--r1);box-shadow:none;transition:background .15s,color .15s}
[data-testid="stSidebar"] .stButton>button:hover{background:rgba(255,255,255,.75);color:var(--ink);border-color:var(--line)}
[data-testid="stSidebar"] [class*="st-key-navactive_"] button{background:var(--surface)!important;color:var(--ink)!important;border-color:var(--line2)!important;
  font-weight:600;box-shadow:var(--shadow);position:relative}
[data-testid="stSidebar"] [class*="st-key-navactive_"] button::before{content:"";position:absolute;left:-1px;top:8px;bottom:8px;width:3px;border-radius:3px;background:var(--teal)}
[data-testid="stSidebar"] [class*="st-key-navactive_"] button span[data-testid="stIconMaterial"]{color:var(--teal)}
.side-status{margin-top:20px;padding:12px;border:1px solid var(--line);border-radius:var(--r2);background:rgba(255,255,255,.6)}
.side-status .row{display:flex;align-items:center;justify-content:space-between;font-size:12.5px;color:var(--ink2);padding:2px 0}
.side-foot{margin-top:18px;padding:0 8px;font-size:11.5px;color:var(--muted);line-height:1.5}

/* ---------- page header ---------- */
.ph{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;padding-bottom:16px;margin-bottom:24px;border-bottom:1px solid var(--line)}
.ph.norule{border-bottom:0;margin-bottom:8px}
.ph h1{font-family:var(--serif);font-weight:600;font-size:28px;margin:0;line-height:1.15;color:var(--ink)}
.ph p{margin:6px 0 0;color:var(--muted);font-size:14px;max-width:62ch}
.eyebrow{font-size:11px;font-weight:600;letter-spacing:.09em;text-transform:uppercase;color:var(--teal);margin-bottom:6px}
.sec{display:flex;align-items:baseline;justify-content:space-between;margin:32px 0 12px}
.sec h2{font-size:16px;margin:0;font-weight:600}
.sec .hint{font-size:12.5px;color:var(--muted)}

/* ---------- stat strip (one panel, not N cards) ---------- */
.strip{display:grid;grid-auto-flow:column;grid-auto-columns:1fr;background:var(--surface);border:1px solid var(--line);border-radius:var(--r2);box-shadow:var(--shadow)}
.strip .s{padding:16px 20px;border-right:1px solid var(--line)}
.strip .s:last-child{border-right:0}
.strip .v{font-size:26px;font-weight:600;letter-spacing:-.02em;color:var(--ink);line-height:1.1;font-variant-numeric:tabular-nums}
.strip .l{font-size:12px;color:var(--muted);margin-top:4px}
.strip .s.emph .v{color:var(--accent)}
@media (max-width:760px){.strip{grid-auto-flow:row}.strip .s{border-right:0;border-bottom:1px solid var(--line)}}

/* ---------- panels, tables ---------- */
.panel{background:var(--surface);border:1px solid var(--line);border-radius:var(--r2);padding:20px 22px;box-shadow:var(--shadow)}
.panel.tight{padding:0}
.panel h3{font-size:14px;margin:0 0 10px;font-weight:600}
.tbl{width:100%;border-collapse:collapse;font-size:13.5px}
.tbl th{text-align:left;font-size:11.5px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);padding:10px 16px;border-bottom:1px solid var(--line);background:var(--bg)}
.tbl td{padding:11px 16px;border-bottom:1px solid var(--line);color:var(--ink);vertical-align:middle}
.tbl tr:last-child td{border-bottom:0}
.tbl tbody tr:hover td{background:#FCFBF8}
.tbl .num{text-align:right;font-variant-numeric:tabular-nums}
.tbl-wrap{overflow-x:auto;border:1px solid var(--line);border-radius:var(--r2);background:var(--surface);box-shadow:var(--shadow)}
.kv{display:grid;grid-template-columns:170px 1fr;gap:8px 16px;font-size:13.5px}
.kv dt{color:var(--muted)} .kv dd{margin:0;color:var(--ink)}
.mono{font-size:12.5px;color:var(--ink2)}

/* ---------- run rows (dashboard) ---------- */
.rr-head{display:grid;grid-template-columns:130px 1.1fr 1.3fr 1.1fr 90px;gap:12px;padding:0 16px 8px;font-size:11.5px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;color:var(--muted)}
[class*="st-key-runrow_"]{background:var(--surface);border:1px solid var(--line);border-radius:var(--r1);padding:6px 16px;margin-bottom:6px;transition:border-color .15s,box-shadow .15s}
[class*="st-key-runrow_"]:hover{border-color:var(--line2);box-shadow:0 2px 6px rgba(11,27,51,.06)}
[class*="st-key-runrow_"] [data-testid="stHorizontalBlock"]{align-items:center;gap:12px}

/* ---------- badges, dots ---------- */
.badge{display:inline-flex;align-items:center;gap:6px;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:600;line-height:1.6;border:1px solid transparent;white-space:nowrap}
.badge .d{width:6px;height:6px;border-radius:50%;background:currentColor}
.b-queued{background:var(--info-bg);color:var(--info);border-color:#D0DBF5}
.b-running{background:var(--warn-bg);color:var(--warn);border-color:#F3DDB2}.b-running .d{animation:pulse 1.4s ease-in-out infinite}
.b-completed,.b-ok{background:var(--ok-bg);color:var(--ok);border-color:#C9E6D0}
.b-escalated,.b-warn{background:var(--warn-bg);color:var(--warn);border-color:#F3DDB2}
.b-failed,.b-bad{background:var(--bad-bg);color:var(--bad);border-color:#F2C9C9}
.b-na{background:var(--neutral-bg);color:var(--ink2);border-color:var(--line2)}
.b-verified{background:var(--teal-bg);color:var(--teal);border-color:#BFE1DB}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:8px;background:var(--line2)}
.dot.ok{background:#1F9D55}.dot.warn{background:#D98A0B}.dot.bad{background:#D03B3B}
@keyframes pulse{50%{opacity:.35}}
@media (prefers-reduced-motion:reduce){.b-running .d{animation:none}}

/* ---------- alerts / outcome ---------- */
.alert{display:flex;gap:12px;padding:14px 16px;border-radius:var(--r2);border:1px solid;font-size:14px;margin:0 0 16px}
.alert svg{flex:none;margin-top:2px}.alert b{display:block;margin-bottom:2px}
.alert.info{background:var(--info-bg);border-color:#D0DBF5;color:var(--info)}
.alert.ok{background:var(--ok-bg);border-color:#C9E6D0;color:var(--ok)}
.alert.warn{background:var(--warn-bg);border-color:#F3DDB2;color:var(--warn)}
.alert.bad{background:var(--bad-bg);border-color:#F2C9C9;color:var(--bad)}
.alert.na{background:repeating-linear-gradient(135deg,#F3EFE6,#F3EFE6 8px,#EFEADF 8px,#EFEADF 16px);border-color:var(--line2);color:var(--ink2)}
.outcome{background:var(--surface);border:1px solid var(--line);border-left:4px solid var(--teal);border-radius:var(--r2);padding:20px 22px;margin-bottom:16px;box-shadow:var(--shadow)}
.outcome.warn{border-left-color:#D98A0B}.outcome.bad{border-left-color:#D03B3B}.outcome.na{border-left-color:var(--line2)}
.outcome .k{font-size:11px;font-weight:600;letter-spacing:.09em;text-transform:uppercase;color:var(--muted)}
.outcome .route{font-family:var(--serif);font-size:22px;font-weight:600;margin:4px 0 10px;color:var(--ink)}
.outcome p{margin:0 0 6px;color:var(--ink2);max-width:75ch}

/* ---------- evidence ---------- */
.cite{background:var(--surface);border:1px solid var(--line);border-radius:var(--r2);padding:16px 18px;margin-bottom:12px;box-shadow:var(--shadow)}
.cite-head{display:flex;flex-wrap:wrap;align-items:center;gap:8px 14px;margin-bottom:10px}
.cite .clause{font-family:var(--mono);font-weight:600;font-size:14px;color:var(--ink)}
.cite .meta{font-size:12.5px;color:var(--muted)}
.cite blockquote{opacity:1!important;font-style:normal!important;margin:0;padding:10px 14px;border-left:3px solid var(--teal);background:var(--sunken);border-radius:0 var(--r1) var(--r1) 0;color:var(--ink)!important;font-size:13.5px;line-height:1.6;overflow-wrap:anywhere}
.cite .src{margin-top:8px;font-size:12px;color:var(--muted);overflow-wrap:anywhere}

/* ---------- stepper + timeline ---------- */
.steps{display:flex;gap:0;margin:0 0 20px;flex-wrap:wrap}
.step{display:flex;align-items:center;gap:8px;padding:6px 14px 6px 0;font-size:13px;font-weight:500;color:var(--muted)}
.step i{width:22px;height:22px;border-radius:50%;display:grid;place-items:center;font-style:normal;font-size:11px;font-weight:700;background:var(--neutral-bg);color:var(--muted);border:1px solid var(--line2)}
.step.done{color:var(--ink)}.step.done i{background:var(--teal);color:#fff;border-color:var(--teal)}
.step.active{color:var(--ink)}.step.active i{background:var(--warn-bg);color:var(--warn);border-color:#E7C98D}
.step.fail{color:var(--bad)}.step.fail i{background:var(--bad-bg);color:var(--bad);border-color:#EBB9B9}
.step.skip{color:#9AA5B5}
.step:not(:last-child)::after{content:"";width:28px;height:1px;background:var(--line2);margin-left:6px}
.tl{list-style:none;margin:0;padding:0;position:relative}
.tl li{position:relative;padding:0 0 14px 22px;font-size:13px;color:var(--ink2)}
.tl li::before{content:"";position:absolute;left:3px;top:6px;width:7px;height:7px;border-radius:50%;background:var(--line2)}
.tl li::after{content:"";position:absolute;left:6px;top:14px;bottom:-2px;width:1px;background:var(--line)}
.tl li:last-child::after{display:none}
.tl li.hl::before{background:var(--teal)}.tl li.bad::before{background:#D03B3B}.tl li.warn::before{background:#D98A0B}
.tl .t{font-family:var(--mono);font-size:11.5px;color:var(--muted);margin-right:8px}.tl b{color:var(--ink);font-weight:600}

/* ---------- empty / form / buttons ---------- */
.empty{text-align:center;padding:40px 16px;border:1px dashed var(--line2);border-radius:var(--r2);background:rgba(255,255,255,.5);color:var(--muted)}
.empty b{display:block;color:var(--ink);font-size:15px;margin-bottom:4px}
.fs{font-size:12px;font-weight:600;letter-spacing:.07em;text-transform:uppercase;color:var(--teal);margin:6px 0 2px}
.fd{font-size:13px;color:var(--muted);margin:0 0 12px}
.ferr{color:var(--bad);font-size:12.5px;margin:-8px 0 10px;display:flex;gap:6px;align-items:center}
.stTextInput input,.stNumberInput input,.stTextArea textarea,[data-baseweb="select"]>div{background:var(--surface)!important;border-color:var(--line2)!important;border-radius:var(--r1)!important;color:var(--ink)!important}
.stTextInput input:focus,.stNumberInput input:focus,.stTextArea textarea:focus{border-color:var(--teal)!important;box-shadow:0 0 0 3px rgba(15,118,110,.18)!important}
label,[data-testid="stWidgetLabel"] p{font-size:13px!important;font-weight:500!important;color:var(--ink2)!important}
.main .stButton>button,.stFormSubmitButton>button{border-radius:var(--r1);font-weight:600;font-size:14px;padding:.45rem 1rem;border:1px solid var(--line2);background:var(--surface);color:var(--ink);transition:background .15s,border-color .15s,box-shadow .15s}
.main .stButton>button:hover,.stFormSubmitButton>button:hover{border-color:var(--ink2);background:#fff;box-shadow:var(--shadow)}
[data-testid="stBaseButton-primary"],[data-testid="stBaseButton-primaryFormSubmit"]{background:var(--accent)!important;border-color:var(--accent)!important;color:#fff!important}
[data-testid="stBaseButton-primary"]:hover,[data-testid="stBaseButton-primaryFormSubmit"]:hover{background:var(--accent-h)!important;border-color:var(--accent-h)!important}
[data-testid="stBaseButton-primary"] p,[data-testid="stBaseButton-primaryFormSubmit"] p{color:#fff!important}
button:disabled{opacity:.55!important;cursor:not-allowed!important}
[data-testid="stForm"]{border:1px solid var(--line);border-radius:var(--r2);background:var(--surface);padding:24px 26px;box-shadow:var(--shadow)}
[role="tablist"]{gap:4px;border-bottom:1px solid var(--line)}
[data-testid="stTab"]{color:var(--muted)!important}
[data-testid="stTab"] p{color:inherit!important;font-weight:500}
[data-testid="stTab"][aria-selected="true"]{color:var(--ink)!important}
[data-testid="stTab"][aria-selected="true"] p{font-weight:600}
.react-aria-SelectionIndicator{background-color:var(--teal)!important}
[data-baseweb="tab"]{font-weight:500;color:var(--muted)}
[aria-selected="true"][data-baseweb="tab"]{color:var(--ink);font-weight:600}
[data-baseweb="tab-highlight"]{background:var(--teal)!important}
[data-testid="stVegaLiteChart"],[data-testid="stArrowVegaLiteChart"]{background:transparent}
@media (max-width:760px){.block-container{padding:1.25rem 1rem 2rem!important}.ph{flex-direction:column;align-items:flex-start}.kv{grid-template-columns:1fr}.rr-head{display:none}}
</style>
"""
