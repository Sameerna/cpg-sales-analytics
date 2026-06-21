"""
CPG Revenue Intelligence Platform — Streamlit Dashboard
Numbers-first management view. Max 1 chart per tab. Data tables dominate.

Run:
    uvicorn api.main:app --reload &
    streamlit run dashboard/app.py
"""
import os
import re
from datetime import datetime
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import streamlit as st

# ─────────────────────────────────────────────────────────────────────────────
# Config — reads from env (local/Docker) or st.secrets (Streamlit Cloud)
# ─────────────────────────────────────────────────────────────────────────────
def _cfg(key: str, default: str) -> str:
    return os.getenv(key) or st.secrets.get(key, default)

API_BASE = _cfg("API_BASE", "http://localhost:8000")
API_KEY  = _cfg("API_KEY", "dev-key")
HEADERS  = {"X-API-Key": API_KEY}

REGION_MAP      = {"North": "NA", "South": "LATAM", "East": "APAC", "West": "EMEA"}
REGION_REVERSE  = {v: k for k, v in REGION_MAP.items()}
ALL_REGIONS     = ["NA", "LATAM", "APAC", "EMEA"]
ALL_CATEGORIES  = ["Beverages", "Snacks", "Dairy", "Personal Care", "Household"]
ALL_YEARS       = ["2022", "2023", "2024", "2025", "2026"]
MONTH_NAMES     = {
    1:"Jan",2:"Feb",3:"Mar",4:"Apr",5:"May",6:"Jun",
    7:"Jul",8:"Aug",9:"Sep",10:"Oct",11:"Nov",12:"Dec",
}

PRIMARY  = "#2563EB"
GREEN    = "#059669"
RED      = "#DC2626"
AMBER    = "#D97706"
SLATE    = "#64748B"
BORDER   = "#E2E8F0"

CAT_COLORS = [PRIMARY, "#7C3AED", GREEN, AMBER, RED]

SUGGESTED_QUESTIONS = [
    "Which category has the strongest momentum?",
    "Which regions are underperforming?",
    "What does marketing efficiency tell us?",
    "Which category should get next quarter's budget?",
    "Did the 2025 price hike hurt Beverages volume?",
]

# ─────────────────────────────────────────────────────────────────────────────
# Page setup
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="CPG Analytics", page_icon="📊",
                   layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

html, body, [class*="css"] { font-family:'Inter',sans-serif !important; }
.stApp { background:#F8FAFC; }
#MainMenu, footer, header { visibility:hidden; }
.block-container { padding:1.25rem 2rem 2rem 2rem !important; }

/* ── KPI cards ── */
[data-testid="metric-container"] {
    background:white; border-radius:12px; padding:20px 22px;
    border:1px solid #E2E8F0; box-shadow:0 1px 3px rgba(15,23,42,.05);
}
[data-testid="metric-container"] label {
    color:#64748B !important; font-size:.68rem !important;
    font-weight:700 !important; letter-spacing:.08em !important;
    text-transform:uppercase !important;
}
[data-testid="metric-container"] [data-testid="metric-value"] {
    font-size:2.1rem !important; font-weight:800 !important; color:#0F172A !important;
}

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {
    gap:0; background:transparent; border-bottom:2px solid #E2E8F0; padding-bottom:0;
}
.stTabs [data-baseweb="tab"] {
    background:transparent; border:none; border-bottom:3px solid transparent;
    margin-bottom:-2px; color:#64748B; font-weight:500; font-size:.85rem;
    padding:10px 22px; border-radius:0;
}
.stTabs [aria-selected="true"] {
    background:transparent !important; color:#2563EB !important;
    border-bottom-color:#2563EB !important; font-weight:700 !important;
}

/* ── Number table ── */
.num-table { width:100%; border-collapse:collapse; font-size:.85rem; }
.num-table thead th {
    background:#F8FAFC; color:#64748B; font-weight:600; font-size:.7rem;
    text-transform:uppercase; letter-spacing:.07em; padding:10px 14px;
    border-bottom:2px solid #E2E8F0; text-align:left;
}
.num-table tbody td { padding:11px 14px; border-bottom:1px solid #F1F5F9; color:#0F172A; }
.num-table tbody tr:last-child td { border-bottom:none; }
.num-table tbody tr:hover td { background:#F8FAFC; }
.table-card {
    background:white; border:1px solid #E2E8F0; border-radius:12px;
    padding:0; overflow:hidden; margin-bottom:20px;
}
.table-title {
    font-size:.72rem; font-weight:700; color:#64748B;
    text-transform:uppercase; letter-spacing:.09em;
    padding:14px 16px 10px 16px; border-bottom:1px solid #F1F5F9;
}

/* ── Filter dialog internals ── */
div[data-testid="stRadio"] > label { display:none !important; }
div[data-testid="stRadio"] [role="radiogroup"] {
    display:flex !important; flex-direction:row !important; gap:6px; flex-wrap:wrap;
}
div[data-testid="stRadio"] [role="radiogroup"] > label {
    background:#F1F5F9; border:1px solid #E2E8F0; border-radius:7px;
    padding:6px 16px; font-size:.8rem; color:#64748B;
    cursor:pointer; transition:all .15s; font-weight:500;
    white-space:nowrap; margin:0 !important;
}
div[data-testid="stRadio"] [role="radiogroup"] > label:has(input:checked) {
    background:#2563EB !important; border-color:#2563EB !important;
    color:white !important; font-weight:700 !important;
}
div[data-testid="stRadio"] [role="radiogroup"] input { display:none !important; }

/* Multiselect compact tags */
[data-baseweb="tag"] {
    background:#EFF6FF !important; border:1px solid #BFDBFE !important;
    border-radius:5px !important; height:22px !important;
    padding:0 8px !important; margin:1px !important;
}
[data-baseweb="tag"] > span {
    color:#1E40AF !important; font-size:.71rem !important;
    font-weight:600 !important; line-height:22px !important;
}
[data-baseweb="tag"] button svg { fill:#3B82F6 !important; width:10px !important; height:10px !important; }
[data-baseweb="select"] > div:first-child {
    border-color:#E2E8F0 !important; border-radius:8px !important;
    min-height:38px !important; background:white !important;
}
[data-baseweb="select"] > div:first-child:focus-within {
    border-color:#93C5FD !important;
    box-shadow:0 0 0 3px rgba(37,99,235,.12) !important;
}

/* ── AI search card ── */
.ai-card {
    background:white; border:1px solid #E2E8F0; border-radius:14px;
    overflow:hidden; margin:20px 0 0 0;
    box-shadow:0 2px 12px rgba(15,23,42,.06);
}
.ai-card-header {
    background:linear-gradient(135deg,#1E3A5F 0%,#1D4ED8 100%);
    padding:16px 22px 14px 22px;
    display:flex; align-items:center; gap:12px;
}
.ai-card-icon {
    width:34px; height:34px; background:rgba(255,255,255,.15);
    border:1px solid rgba(255,255,255,.25);
    border-radius:9px; display:flex; align-items:center;
    justify-content:center; font-size:16px; flex-shrink:0;
}
.ai-card-title { font-size:.95rem; font-weight:700; color:white; margin:0; }
.ai-card-sub   { font-size:.71rem; color:rgba(255,255,255,.55); margin:2px 0 0 0; }
.ai-card-body  { padding:14px 20px 16px 20px; }
.ai-chips-label {
    font-size:.64rem; font-weight:700; color:#94A3B8;
    text-transform:uppercase; letter-spacing:.09em;
    margin-bottom:9px; display:block;
}

/* ── All primary buttons → brand blue ── */
[data-testid="baseButton-primary"],
[data-testid="stBaseButton-primary"],
.stButton > button[kind="primary"] {
    background:#2563EB !important; border-color:#2563EB !important;
    color:white !important; border-radius:8px !important;
    font-weight:600 !important;
}
[data-testid="baseButton-primary"]:hover,
[data-testid="stBaseButton-primary"]:hover,
.stButton > button[kind="primary"]:hover {
    background:#1D4ED8 !important; border-color:#1D4ED8 !important;
}

/* ── Chip / secondary buttons inside columns → light blue pill ── */
div[data-testid="column"] [data-testid="baseButton-secondary"],
div[data-testid="column"] [data-testid="stBaseButton-secondary"],
div[data-testid="column"] .stButton > button[kind="secondary"],
div[data-testid="column"] .stButton > button:not([kind="primary"]) {
    background:#EFF6FF !important; border:1px solid #BFDBFE !important;
    border-radius:20px !important; color:#1D4ED8 !important;
    font-size:.73rem !important; font-weight:500 !important;
    padding:4px 14px !important; white-space:normal !important;
    height:auto !important; line-height:1.4 !important; transition:all .15s !important;
}
div[data-testid="column"] [data-testid="baseButton-secondary"]:hover,
div[data-testid="column"] [data-testid="stBaseButton-secondary"]:hover,
div[data-testid="column"] .stButton > button[kind="secondary"]:hover,
div[data-testid="column"] .stButton > button:not([kind="primary"]):hover {
    background:#2563EB !important; color:white !important; border-color:#2563EB !important;
}

/* ── Text input → always white background ── */
[data-testid="stTextInput"] input,
[data-testid="stTextInput"] > div > div > input {
    background:white !important; color:#0F172A !important;
    border-color:#E2E8F0 !important; border-radius:8px !important;
    font-size:.88rem !important;
}
[data-testid="stTextInput"] input:focus,
[data-testid="stTextInput"] > div > div > input:focus {
    border-color:#93C5FD !important;
    box-shadow:0 0 0 3px rgba(37,99,235,.12) !important;
}

/* ── AI answer card ── */
.ai-answer {
    background:#F8FAFF; border-radius:10px; padding:16px 20px;
    border-left:4px solid #2563EB; margin-top:14px;
    font-size:.88rem; color:#0F172A; line-height:1.75;
}
.ai-answer-q {
    font-size:.67rem; font-weight:700; color:#2563EB;
    text-transform:uppercase; letter-spacing:.08em; margin-bottom:8px;
}

/* Sidebar — hidden */
[data-testid="stSidebar"] { display:none; }

/* ── Loading card ── */
@keyframes cpg-spin { to { transform:rotate(360deg); } }
@keyframes cpg-pulse { 0%,100%{opacity:1;} 50%{opacity:.45;} }
.ai-loading {
    background:white; border:1px solid #E2E8F0; border-radius:14px;
    padding:20px 22px; margin:16px 0 0 0;
    display:flex; align-items:center; gap:16px;
    box-shadow:0 2px 12px rgba(15,23,42,.06);
}
.ai-loading-spinner {
    width:34px; height:34px; flex-shrink:0;
    border:3px solid #BFDBFE; border-top-color:#2563EB;
    border-radius:50%; animation:cpg-spin .75s linear infinite;
}
.ai-loading-label { font-size:.88rem; font-weight:600; color:#0F172A; }
.ai-loading-sub   { font-size:.72rem; color:#94A3B8; margin-top:3px;
                    animation:cpg-pulse 1.6s ease-in-out infinite; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# Session state
# ─────────────────────────────────────────────────────────────────────────────
if "answers" not in st.session_state:
    st.session_state.answers = []  # list of {q, exec_brief, ai_para, deep, is_custom_q}
if "pending_q" not in st.session_state:
    st.session_state.pending_q = ""
if "is_custom_q" not in st.session_state:
    st.session_state.is_custom_q = False
if "filter_year" not in st.session_state:
    st.session_state.filter_year = "All"
if "filter_month" not in st.session_state:
    st.session_state.filter_month = "All Months"
if "filter_cat" not in st.session_state:
    st.session_state.filter_cat = ALL_CATEGORIES[:]
if "filter_reg" not in st.session_state:
    st.session_state.filter_reg = ALL_REGIONS[:]

# ─────────────────────────────────────────────────────────────────────────────
# Filter drawer
# ─────────────────────────────────────────────────────────────────────────────
@st.dialog("Filters", width="small")
def open_filters() -> None:
    st.markdown("**Year**")
    yr = st.radio(
        "Year", ["All"] + ALL_YEARS,
        index=(["All"] + ALL_YEARS).index(st.session_state.filter_year)
              if st.session_state.filter_year in (["All"] + ALL_YEARS) else 0,
        horizontal=True, label_visibility="collapsed", key="dlg_year",
    )

    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    st.markdown("**Month**")
    month_opts = ["All Months"] + [MONTH_NAMES[m] for m in range(1, 13)]
    mo_idx = month_opts.index(st.session_state.filter_month) if st.session_state.filter_month in month_opts else 0
    mo = st.selectbox("Month", month_opts, index=mo_idx,
                      label_visibility="collapsed", key="dlg_month")

    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    st.markdown("**Category**")
    cat = st.multiselect("Category", ALL_CATEGORIES,
                         default=st.session_state.filter_cat or ALL_CATEGORIES,
                         label_visibility="collapsed", key="dlg_cat",
                         placeholder="All categories")

    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    st.markdown("**Region**")
    reg = st.multiselect("Region", ALL_REGIONS,
                         default=st.session_state.filter_reg or ALL_REGIONS,
                         label_visibility="collapsed", key="dlg_reg",
                         placeholder="All regions")

    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
    apply_col, reset_col = st.columns(2)
    if apply_col.button("Apply", type="primary", use_container_width=True):
        st.session_state.filter_year  = yr
        st.session_state.filter_month = mo
        st.session_state.filter_cat   = cat or ALL_CATEGORIES[:]
        st.session_state.filter_reg   = reg or ALL_REGIONS[:]
        st.rerun()
    if reset_col.button("Reset", use_container_width=True):
        st.session_state.filter_year  = "All"
        st.session_state.filter_month = "All Months"
        st.session_state.filter_cat   = ALL_CATEGORIES[:]
        st.session_state.filter_reg   = ALL_REGIONS[:]
        st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# API helpers
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=120)
def fetch_metrics() -> Optional[dict]:
    try:
        r = requests.get(f"{API_BASE}/metrics", headers=HEADERS, timeout=10)
        r.raise_for_status(); return r.json()
    except Exception: return None

@st.cache_data(ttl=120)
def fetch_summary() -> Optional[dict]:
    try:
        r = requests.get(f"{API_BASE}/data/summary", headers=HEADERS, timeout=10)
        r.raise_for_status(); return r.json()
    except Exception: return None

def call_insights_local(question: str) -> Optional[dict]:
    """Always uses the local SQL analytics engine regardless of USE_LLM."""
    try:
        r = requests.post(
            f"{API_BASE}/insights",
            json={"question": question, "force_local": True},
            headers=HEADERS,
            timeout=30,
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        return {"insight": f"Local analysis error: {exc}", "llm_used": False}


def call_exec_brief(question: str) -> Optional[dict]:
    """Returns structured executive brief from /insights/exec."""
    try:
        r = requests.post(
            f"{API_BASE}/insights/exec",
            json={"question": question},
            headers=HEADERS,
            timeout=30,
        )
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def stream_insights_generator(question: str):
    """Yields text chunks from the streaming Claude endpoint."""
    try:
        r = requests.post(
            f"{API_BASE}/insights/stream",
            json={"question": question},
            headers=HEADERS,
            stream=True,
            timeout=120,
        )
        if r.status_code == 503:
            try:
                detail = r.json().get("detail", "LLM is disabled.")
            except Exception:
                detail = "LLM is disabled."
            yield (
                f"**{detail}**\n\n"
                "The **Executive Summary** tab uses the local analytics engine "
                "with real data and is always available."
            )
            return
        r.raise_for_status()
        for chunk in r.iter_content(chunk_size=None, decode_unicode=True):
            if chunk:
                yield chunk
    except Exception as exc:
        yield f"\n\n*Connection error: {exc}*"


def stream_exec_ai_generator(question: str):
    """Yields text chunks from the short AI synthesis endpoint for the exec brief."""
    try:
        r = requests.post(
            f"{API_BASE}/insights/exec-ai",
            json={"question": question},
            headers=HEADERS,
            stream=True,
            timeout=60,
        )
        if r.status_code == 503:
            yield "*AI synthesis unavailable — set USE_LLM=true in .env to enable.*"
            return
        r.raise_for_status()
        for chunk in r.iter_content(chunk_size=None, decode_unicode=True):
            if chunk:
                yield chunk
    except Exception as exc:
        yield f"*Connection error: {exc}*"

# ─────────────────────────────────────────────────────────────────────────────
# Chart helper
# ─────────────────────────────────────────────────────────────────────────────
def styled(fig: go.Figure, title: str = "", height: int = 280) -> go.Figure:
    fig.update_layout(
        title=dict(
            text=f"<span style='font-size:12px;color:#1E293B;font-weight:700;'>{title}</span>" if title else "",
            x=0, xanchor="left", font=dict(family="Inter"),
        ),
        plot_bgcolor="white", paper_bgcolor="white",
        font_family="Inter", height=height,
        margin=dict(l=4, r=4, t=44 if title else 8, b=4),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                    font=dict(size=10, color=SLATE), bgcolor="rgba(0,0,0,0)"),
        hoverlabel=dict(bgcolor="white", font_size=12, font_family="Inter", bordercolor=BORDER),
    )
    fig.update_xaxes(showgrid=False, linecolor=BORDER, tickfont=dict(size=10, color=SLATE))
    fig.update_yaxes(gridcolor="#F1F5F9", linecolor="rgba(0,0,0,0)", tickfont=dict(size=10, color=SLATE))
    return fig

CHART_CFG = {"displayModeBar": False}

LOGO = """<svg width="36" height="36" viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect width="40" height="40" rx="10" fill="url(#g1)"/>
  <defs><linearGradient id="g1" x1="0" y1="0" x2="40" y2="40" gradientUnits="userSpaceOnUse">
    <stop offset="0%" stop-color="#1D4ED8"/><stop offset="100%" stop-color="#7C3AED"/>
  </linearGradient></defs>
  <rect x="8" y="25" width="5" height="9" rx="2" fill="white"/>
  <rect x="17" y="16" width="5" height="18" rx="2" fill="white"/>
  <rect x="26" y="8" width="5" height="26" rx="2" fill="white"/>
  <circle cx="32" cy="6" r="3.5" fill="#34D399"/>
</svg>"""

# ─────────────────────────────────────────────────────────────────────────────
# HTML table helper
# ─────────────────────────────────────────────────────────────────────────────
def render_table(title: str, headers: list, rows: list) -> None:
    """Render a clean, styled HTML table with a card wrapper."""
    th_html = "".join(
        f"<th class='right' style='text-align:{'left' if i==0 else 'right'};'>{h}</th>"
        for i, h in enumerate(headers)
    )
    rows_html = ""
    for row in rows:
        cells = ""
        for i, cell in enumerate(row):
            align = "left" if i == 0 else "right"
            css = f"text-align:{align};"
            # colour-code percent changes
            val = str(cell)
            if val.startswith("+") and "%" in val:
                css += "color:#059669;font-weight:600;"
            elif val.startswith("−") or (val.startswith("-") and "%" in val):
                css += "color:#DC2626;font-weight:600;"
            cells += f"<td style='{css}'>{val}</td>"
        rows_html += f"<tr>{cells}</tr>"

    html = f"""
<div class="table-card">
  <div class="table-title">{title}</div>
  <table class="num-table">
    <thead><tr>{th_html}</tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>"""
    st.markdown(html, unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# Executive brief renderer
# ─────────────────────────────────────────────────────────────────────────────
def _render_exec_brief(question: str, brief: Optional[dict], ai_para: Optional[str] = None) -> str:
    """
    Renders two-part executive brief.
    Returns the AI paragraph text (streamed live if ai_para is None, shown static otherwise).
    """
    st.markdown(
        f"<div class='ai-answer-q' style='margin-bottom:14px;'>✦ {question}</div>",
        unsafe_allow_html=True,
    )
    if not brief:
        st.error("Could not load executive brief — is the API running?")
        return ""

    # ── Part 1: Data Intelligence ──────────────────────────────────────────
    st.markdown(
        "<div style='font-size:.68rem;font-weight:700;color:#059669;"
        "text-transform:uppercase;letter-spacing:.1em;margin:0 0 8px 0;'>"
        "📊 Data Intelligence</div>",
        unsafe_allow_html=True,
    )
    narrative = brief.get("narrative", "")
    if narrative:
        narrative_html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", narrative)
        st.markdown(
            f"<div style='background:#F0FDF4;border-radius:10px;padding:18px 22px;"
            f"border-left:4px solid #059669;margin-bottom:6px;"
            f"font-size:.88rem;line-height:1.8;color:#0F172A;'>{narrative_html}</div>",
            unsafe_allow_html=True,
        )
    st.markdown(
        "<div style='font-size:.67rem;color:#94A3B8;margin:0 0 22px 2px;'>"
        "Computed from row-level transaction data using local ML models · No data sent externally"
        "</div>",
        unsafe_allow_html=True,
    )

    # ── Part 2: AI Synthesis ───────────────────────────────────────────────
    st.markdown(
        "<div style='font-size:.68rem;font-weight:700;color:#2563EB;"
        "text-transform:uppercase;letter-spacing:.1em;margin:0 0 8px 0;'>"
        "✦ AI Synthesis</div>",
        unsafe_allow_html=True,
    )
    result_para = ""
    if ai_para is not None:
        st.markdown(ai_para)
        result_para = ai_para
    else:
        _spin = st.empty()
        _spin.markdown(
            "<span style='color:#94A3B8;font-size:.82rem;'>✦ Claude is synthesising…</span>",
            unsafe_allow_html=True,
        )
        result_para = st.write_stream(stream_exec_ai_generator(question))
        _spin.empty()

    st.markdown(
        "<div style='font-size:.67rem;color:#94A3B8;margin:4px 0 22px 2px;'>"
        "Row-level data is not provided to Claude · AI-generated text based on pre-aggregated statistics only"
        "</div>",
        unsafe_allow_html=True,
    )

    # ── Supporting Evidence expander ──────────────────────────────────────
    evidence = brief.get("evidence", {})
    non_empty = {k: v for k, v in evidence.items() if v.get("rows")}
    if non_empty:
        with st.expander("📊 Supporting Evidence", expanded=False):
            for section_title, section_data in non_empty.items():
                st.markdown(
                    f"<div style='font-size:.7rem;font-weight:700;color:#64748B;"
                    f"text-transform:uppercase;letter-spacing:.09em;"
                    f"margin:14px 0 6px 0;'>{section_title}</div>",
                    unsafe_allow_html=True,
                )
                render_table("", section_data["headers"], section_data["rows"])

    # ── Source Tables expander ────────────────────────────────────────────
    sources = brief.get("sources", [])
    if sources:
        with st.expander("📋 Source Tables", expanded=False):
            layer_order = [
                ("Clean", "#7C3AED", "Cleaned Data Layer"),
                ("Mart",  "#2563EB", "Data Mart Layer"),
                ("ML",    "#059669", "ML Model"),
            ]
            for layer_key, color, label in layer_order:
                layer_items = [s for s in sources if s.get("layer") == layer_key]
                if not layer_items:
                    continue
                st.markdown(
                    f"<div style='font-size:.68rem;font-weight:700;color:{color};"
                    f"text-transform:uppercase;letter-spacing:.1em;margin:12px 0 6px 0;'>"
                    f"▸ {label}</div>",
                    unsafe_allow_html=True,
                )
                for s in layer_items:
                    st.markdown(
                        f"<div style='background:white;border:1px solid #E2E8F0;"
                        f"border-radius:8px;padding:10px 14px;margin-bottom:6px;'>"
                        f"<code style='font-size:.78rem;color:#0F172A;'>{s['table']}</code>"
                        f"<div style='font-size:.72rem;color:#64748B;margin-top:3px;'>"
                        f"{s['provides']}</div></div>",
                        unsafe_allow_html=True,
                    )

    return str(result_para)


# ─────────────────────────────────────────────────────────────────────────────
# Header
# ─────────────────────────────────────────────────────────────────────────────
today_str = datetime.now().strftime("%d %b %Y")
hc1, hc2, hc3 = st.columns([1, 8, 3])
with hc1:
    st.markdown(LOGO, unsafe_allow_html=True)
with hc2:
    st.markdown(
        "<h2 style='margin:0;padding-top:2px;color:#0F172A;font-weight:800;font-size:1.35rem;'>"
        "CPG Revenue Intelligence</h2>"
        "<p style='margin:2px 0 0 0;color:#64748B;font-size:.75rem;'>"
        "Global commercial performance · 2022 – 2026</p>",
        unsafe_allow_html=True,
    )
with hc3:
    badge_col, btn_col = st.columns([3, 2])
    badge_col.markdown(
        f"<div style='text-align:right;padding-top:6px;'>"
        f"<span style='background:#EFF6FF;color:#2563EB;font-size:.7rem;font-weight:700;"
        f"padding:4px 12px;border-radius:20px;border:1px solid #BFDBFE;'>● LIVE</span>"
        f"<p style='color:#94A3B8;font-size:.7rem;margin:5px 0 0 0;'>Updated {today_str}</p></div>",
        unsafe_allow_html=True,
    )
    # Count active filters for badge
    _n_filters = (
        (st.session_state.filter_year != "All") +
        (st.session_state.filter_month != "All Months") +
        (sorted(st.session_state.filter_cat) != sorted(ALL_CATEGORIES)) +
        (sorted(st.session_state.filter_reg) != sorted(ALL_REGIONS))
    )
    _btn_label = f"Filters ({_n_filters})" if _n_filters else "Filters"
    if btn_col.button(_btn_label, type="primary", use_container_width=True):
        open_filters()
st.markdown("<hr style='border-color:#E2E8F0;margin:12px 0 14px 0;'>", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# Load data
# ─────────────────────────────────────────────────────────────────────────────
raw_metrics = fetch_metrics()
raw_summary = fetch_summary()

if not raw_metrics or not raw_summary:
    st.error("Cannot reach the API. Run: `uvicorn api.main:app --reload`")
    st.stop()

m_df_full   = pd.DataFrame(raw_summary["monthly"])
cat_yr_full = pd.DataFrame(raw_summary["by_category"])
m_df_full["period"] = (m_df_full["year"].astype(str) + "-" +
                        m_df_full["month"].astype(str).str.zfill(2))
m_df_full = m_df_full.sort_values("period")

# ─────────────────────────────────────────────────────────────────────────────
# Read active filters from session state (set via Filters drawer)
# ─────────────────────────────────────────────────────────────────────────────
year_filter  = ("All Years" if st.session_state.filter_year == "All"
                else st.session_state.filter_year)
month_filter = st.session_state.filter_month
cat_filter   = st.session_state.filter_cat or ALL_CATEGORIES[:]
reg_filter   = st.session_state.filter_reg or ALL_REGIONS[:]

# ─────────────────────────────────────────────────────────────────────────────
# Apply filters
# ─────────────────────────────────────────────────────────────────────────────
m_df = m_df_full.copy()
if year_filter  != "All Years":
    m_df = m_df[m_df["year"].astype(str) == year_filter]
if month_filter != "All Months":
    mn = {v: k for k, v in MONTH_NAMES.items()}[month_filter]
    m_df = m_df[m_df["month"].astype(int) == mn]

cat_yr_df = cat_yr_full[cat_yr_full["category"].isin(cat_filter)].copy()
if year_filter != "All Years":
    cat_yr_df = cat_yr_df[cat_yr_df["year"].astype(str) == year_filter]

active_db_regions = [REGION_REVERSE.get(r, r) for r in reg_filter]
reg_df_all = pd.DataFrame(raw_metrics["regions"])
reg_df_all["region_display"] = reg_df_all["region"].map(REGION_MAP).fillna(reg_df_all["region"])
reg_df = reg_df_all[reg_df_all["region"].isin(active_db_regions)]

# Derived KPIs
total_rev  = m_df["total_revenue"].sum()
total_tx   = m_df["total_transactions"].sum()

mom_pct: Optional[float] = None
if len(m_df) >= 2:
    srt = m_df.sort_values("period")
    r1, r2 = srt.iloc[-1]["total_revenue"], srt.iloc[-2]["total_revenue"]
    if r2: mom_pct = round((r1 - r2) / r2 * 100, 1)

yoy_delta: Optional[float] = None
yr_t = (cat_yr_full[cat_yr_full["category"].isin(cat_filter)]
        .groupby("year")["total_revenue"].sum().sort_index())
if len(yr_t) >= 2:
    ly, py = yr_t.iloc[-1], yr_t.iloc[-2]
    if py: yoy_delta = round((ly - py) / py * 100, 1)

all_years_sorted = sorted(cat_yr_full["year"].astype(str).unique())

# ─────────────────────────────────────────────────────────────────────────────
# AI Search — elegant card
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="ai-card">
  <div class="ai-card-header">
    <div class="ai-card-icon">✦</div>
    <div>
      <div class="ai-card-title">Ask the Data</div>
      <div class="ai-card-sub">Privacy-safe · Claude sees only aggregated statistics, never raw records</div>
    </div>
  </div>
  <div class="ai-card-body">
    <span class="ai-chips-label">Suggested questions</span>
  </div>
</div>
""", unsafe_allow_html=True)

# Chips inside the card body (rendered as Streamlit buttons)
chip_cols = st.columns(len(SUGGESTED_QUESTIONS))
for i, (col, q) in enumerate(zip(chip_cols, SUGGESTED_QUESTIONS)):
    if col.button(q, key=f"chip_{i}", use_container_width=True):
        st.session_state.pending_q = q
        st.session_state.is_custom_q = False  # suggested → Executive Summary first

ai_inp_col, ai_btn_col, ai_clr_col = st.columns([8, 1, 1])
ai_input = ai_inp_col.text_input(
    "ai_input", label_visibility="collapsed",
    placeholder="Ask anything — grounded with real portfolio data, written by Claude",
    key="ai_text",
)
ask_btn   = ai_btn_col.button("Ask", type="primary", use_container_width=True)
clear_btn = ai_clr_col.button("Clear", use_container_width=True)

if clear_btn:
    st.session_state.answers = []
    st.rerun()

q_to_ask = ""
if ask_btn and ai_input.strip():
    q_to_ask = ai_input.strip()
    st.session_state.is_custom_q = True  # typed question → Deep Think first
elif st.session_state.pending_q:
    q_to_ask = st.session_state.pending_q
    st.session_state.pending_q = ""
    # is_custom_q already set when chip was clicked

_SUMMARY_STYLE = (
    "font-family:'JetBrains Mono','Courier New',monospace;"
    "font-size:.81rem;line-height:1.65;background:#F8FAFF;border-radius:8px;"
    "padding:16px 18px;border-left:3px solid #2563EB;white-space:pre-wrap;"
    "overflow-x:auto;margin:0;"
)

if q_to_ask:
    # ── Show spinner immediately so the browser never goes blank ──────────
    _loading = st.empty()
    _loading.markdown(
        f"<div class='ai-loading'>"
        f"<div class='ai-loading-spinner'></div>"
        f"<div>"
        f"<div class='ai-loading-label'>Analysing portfolio data…</div>"
        f"<div class='ai-loading-sub'>✦ {q_to_ask}</div>"
        f"</div></div>",
        unsafe_allow_html=True,
    )

    # ── Executive Summary: structured brief from local data ───────────────
    exec_brief = call_exec_brief(q_to_ask)
    _loading.empty()

    # ── Two-tab answer (order depends on question source) ────────────────
    is_custom = st.session_state.is_custom_q
    if is_custom:
        # Custom typed question → Deep Think is the default (first) tab
        ans_tab_deep, ans_tab_sum = st.tabs(["✦ Deep Think", "⚡ Executive Summary"])
    else:
        # Suggested chip → Executive Summary is the default (first) tab
        ans_tab_sum, ans_tab_deep = st.tabs(["⚡ Executive Summary", "✦ Deep Think"])

    with ans_tab_sum:
        # streams AI Synthesis live and returns the text
        ai_para = _render_exec_brief(q_to_ask, exec_brief)
    with ans_tab_deep:
        st.markdown(
            f"<div class='ai-answer-q' style='margin-bottom:10px;'>✦ {q_to_ask}</div>",
            unsafe_allow_html=True,
        )
        _thinking = st.empty()
        _thinking.markdown(
            "<span style='color:#94A3B8;font-size:.82rem;'>✦ Claude is thinking…</span>",
            unsafe_allow_html=True,
        )
        deep_text = st.write_stream(stream_insights_generator(q_to_ask))
        _thinking.empty()

    st.session_state.answers.append({
        "q": q_to_ask, "exec_brief": exec_brief,
        "ai_para": ai_para, "deep": str(deep_text),
        "is_custom_q": is_custom,
    })

elif st.session_state.answers:
    # ── Show stored last answer ───────────────────────────────────────────
    last = st.session_state.answers[-1]
    is_custom = last.get("is_custom_q", False)
    if is_custom:
        ans_tab_deep, ans_tab_sum = st.tabs(["✦ Deep Think", "⚡ Executive Summary"])
    else:
        ans_tab_sum, ans_tab_deep = st.tabs(["⚡ Executive Summary", "✦ Deep Think"])
    with ans_tab_sum:
        _render_exec_brief(last["q"], last.get("exec_brief"), ai_para=last.get("ai_para", ""))
    with ans_tab_deep:
        st.markdown(
            f"<div class='ai-answer-q' style='margin-bottom:10px;'>✦ {last['q']}</div>",
            unsafe_allow_html=True,
        )
        st.markdown(last["deep"])

st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# TABS
# ─────────────────────────────────────────────────────────────────────────────
tab_kpi, tab_rev, tab_promo = st.tabs(
    ["  KPI Overview  ", "  Revenue  ", "  Promo Insights  "]
)

# ═════════════════════════════════════════════════════════════════════════════
# TAB 1 — KPI Overview
# ═════════════════════════════════════════════════════════════════════════════
with tab_kpi:
    # ── 4 KPI cards ──────────────────────────────────────────────────────────
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Revenue",      f"${total_rev/1e6:.2f}M")
    k2.metric("Total Transactions", f"{total_tx:,}")
    k3.metric(
        "Period-on-Period",
        f"{mom_pct:+.1f}%" if mom_pct is not None else "—",
        delta=f"{mom_pct:.1f}%" if mom_pct is not None else None,
        delta_color="normal",
    )
    k4.metric(
        "Full-Year YoY",
        f"{yoy_delta:+.1f}%" if yoy_delta is not None else "—",
        delta=f"{yoy_delta:.1f}%" if yoy_delta is not None else None,
        delta_color="normal",
    )

    st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

    # ── Category breakdown table ──────────────────────────────────────────────
    cat_totals = (cat_yr_df.groupby("category")
                  .agg(total_revenue=("total_revenue","sum"),
                       avg_discount=("avg_discount_pct","mean"),
                       avg_mktg=("avg_marketing_spend","mean"))
                  .reset_index())

    # YoY per category — use last two complete years (12 months each) to avoid
    # partial-year distortion (e.g. 2026 with only 4 months vs full-year 2025)
    yoy_by_cat: dict = {}
    complete_years = sorted(
        str(int(yr)) for yr, cnt in
        m_df_full.groupby("year")["month"].nunique().items()
        if cnt >= 12
    )
    if len(complete_years) >= 2:
        ldf = cat_yr_full[cat_yr_full["year"].astype(str)==complete_years[-1]].set_index("category")["total_revenue"]
        pdf = cat_yr_full[cat_yr_full["year"].astype(str)==complete_years[-2]].set_index("category")["total_revenue"]
        for cat in ldf.index:
            if cat in pdf.index and pdf[cat]:
                yoy_by_cat[cat] = (ldf[cat] - pdf[cat]) / pdf[cat] * 100

    grand_total = cat_totals["total_revenue"].sum() or 1

    rows = []
    for _, row in cat_totals.sort_values("total_revenue", ascending=False).iterrows():
        cat  = row["category"]
        rev  = row["total_revenue"]
        share = rev / grand_total * 100
        yoy  = yoy_by_cat.get(cat)
        yoy_str = (f"+{yoy:.1f}%" if yoy and yoy >= 0 else f"{yoy:.1f}%" if yoy is not None else "—")
        rows.append([
            cat,
            f"${rev/1e3:,.0f}K",
            f"{share:.1f}%",
            yoy_str,
            f"${row['avg_mktg']:,.0f}/mo",
            f"{row['avg_discount']:.1f}%",
        ])

    render_table(
        "Category Performance",
        ["Category", "Revenue", "Portfolio Share", "YoY Growth", "Avg Mktg Spend", "Avg Discount"],
        rows,
    )

    # ── Regional summary table ────────────────────────────────────────────────
    reg_total = reg_df["total_revenue"].sum() or 1
    reg_rows = [
        [
            r["region_display"],
            f"${r['total_revenue']/1e3:,.0f}K",
            f"{r['total_revenue']/reg_total*100:.1f}%",
        ]
        for _, r in reg_df.sort_values("total_revenue", ascending=False).iterrows()
    ]
    render_table("Regional Revenue", ["Region", "Revenue", "Share"], reg_rows)

    # ── ONE chart: revenue trend ──────────────────────────────────────────────
    if not m_df.empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=m_df["period"], y=m_df["total_revenue"],
            mode="lines",
            line=dict(color=PRIMARY, width=2.5, shape="spline"),
            fill="tozeroy", fillcolor="rgba(37,99,235,0.07)",
            hovertemplate="<b>%{x}</b><br>$%{y:,.0f}<extra></extra>",
        ))
        styled(fig, "Monthly Revenue Trend", height=260)
        fig.update_yaxes(tickprefix="$", tickformat=",.0s")
        fig.update_xaxes(nticks=12)
        st.plotly_chart(fig, use_container_width=True, config=CHART_CFG)

# ═════════════════════════════════════════════════════════════════════════════
# TAB 2 — Revenue
# ═════════════════════════════════════════════════════════════════════════════
with tab_rev:
    # ── Monthly numbers table (last 12 months) ────────────────────────────────
    recent = m_df.sort_values("period", ascending=False).head(12).sort_values("period")
    recent["MoM"] = recent["total_revenue"].pct_change() * 100

    monthly_rows = []
    for _, r in recent.sort_values("period", ascending=False).iterrows():
        mom = r["MoM"]
        mom_str = (f"+{mom:.1f}%" if pd.notna(mom) and mom >= 0
                   else f"{mom:.1f}%" if pd.notna(mom) else "—")
        monthly_rows.append([
            f"{MONTH_NAMES.get(int(r['month']), r['month'])} {r['year']}",
            f"${r['total_revenue']:,.0f}",
            f"{int(r['total_transactions']):,}",
            f"${r['avg_unit_price']:.2f}",
            mom_str,
        ])

    render_table(
        "Monthly Performance (most recent first)",
        ["Period", "Revenue", "Transactions", "Avg Unit Price", "MoM Change"],
        monthly_rows,
    )

    # ── Annual summary numbers ────────────────────────────────────────────────
    ann = (cat_yr_full[cat_yr_full["category"].isin(cat_filter)]
           .groupby("year")
           .agg(revenue=("total_revenue","sum"),
                avg_discount=("avg_discount_pct","mean"),
                avg_mktg=("avg_marketing_spend","mean"))
           .reset_index()
           .sort_values("year", ascending=False))

    # pct_change(-1) on descending sort compares each row to the prior year row;
    # mark the current (partial) year with "—" to avoid misleading comparisons
    ann_sorted_asc = ann.sort_values("year", ascending=True)
    ann_sorted_asc["YoY"] = ann_sorted_asc["revenue"].pct_change(1) * 100
    ann = ann_sorted_asc.sort_values("year", ascending=False)
    max_yr = ann["year"].max()
    ann_rows = []
    for _, r in ann.iterrows():
        yoy = r["YoY"]
        # suppress YoY for the partial current year to avoid distortion
        if r["year"] == max_yr and yoy is not None and yoy < -20:
            yoy = None
        yoy_str = (f"+{yoy:.1f}%" if pd.notna(yoy) and yoy is not None and yoy >= 0
                   else f"{yoy:.1f}%" if pd.notna(yoy) and yoy is not None else "—")
        ann_rows.append([
            str(int(r["year"])),
            f"${r['revenue']/1e6:.2f}M",
            yoy_str,
            f"${r['avg_mktg']:,.0f}/mo",
            f"{r['avg_discount']:.1f}%",
        ])

    render_table(
        "Annual Summary",
        ["Year", "Total Revenue", "YoY Growth", "Avg Mktg Spend", "Avg Discount"],
        ann_rows,
    )

    # ── ONE chart: revenue + transactions dual-axis ───────────────────────────
    if not m_df.empty:
        st.markdown(
            "<p style='font-size:.72rem;font-weight:700;color:#64748B;"
            "text-transform:uppercase;letter-spacing:.09em;margin:8px 0 4px 0;'>"
            "Revenue vs Transaction Volume</p>",
            unsafe_allow_html=True,
        )
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(go.Bar(
            x=m_df["period"], y=m_df["total_revenue"],
            name="Revenue ($)", marker_color=PRIMARY, opacity=0.82,
            hovertemplate="<b>%{x}</b><br>$%{y:,.0f}<extra></extra>",
        ), secondary_y=False)
        fig.add_trace(go.Scatter(
            x=m_df["period"], y=m_df["total_transactions"],
            name="Transactions", line=dict(color=AMBER, width=2.5),
            mode="lines+markers", marker=dict(size=4),
            hovertemplate="<b>%{x}</b><br>%{y:,}<extra></extra>",
        ), secondary_y=True)
        fig.update_layout(
            plot_bgcolor="white", paper_bgcolor="white",
            font_family="Inter", height=300,
            margin=dict(l=4, r=4, t=8, b=4),
            legend=dict(
                orientation="h", x=0, y=-0.18,
                font=dict(size=11, color=SLATE),
                bgcolor="rgba(0,0,0,0)",
            ),
            hoverlabel=dict(bgcolor="white", font_size=12, font_family="Inter", bordercolor=BORDER),
        )
        fig.update_xaxes(showgrid=False, linecolor=BORDER, tickfont=dict(size=10, color=SLATE), nticks=12)
        fig.update_yaxes(tickprefix="$", tickformat=",.0s", gridcolor="#F1F5F9",
                         linecolor="rgba(0,0,0,0)", tickfont=dict(size=10, color=SLATE),
                         secondary_y=False)
        fig.update_yaxes(showgrid=False, linecolor="rgba(0,0,0,0)",
                         tickfont=dict(size=10, color=AMBER), secondary_y=True)
        st.plotly_chart(fig, use_container_width=True, config=CHART_CFG)

# ═════════════════════════════════════════════════════════════════════════════
# TAB 3 — Promo Insights
# ═════════════════════════════════════════════════════════════════════════════
with tab_promo:
    if cat_yr_df.empty:
        st.info("No data for selected filters.")
        st.stop()

    # ── Promo KPI cards ───────────────────────────────────────────────────────
    avg_disc  = cat_yr_df["avg_discount_pct"].mean()
    avg_mktg  = cat_yr_df["avg_marketing_spend"].mean()

    disc_delta_pp: Optional[float] = None
    mktg_pct: Optional[float] = None
    if len(all_years_sorted) >= 2:
        base = cat_yr_full[cat_yr_full["category"].isin(cat_filter)]
        d_l  = base[base["year"].astype(str)==all_years_sorted[-1]]["avg_discount_pct"].mean()
        d_p  = base[base["year"].astype(str)==all_years_sorted[-2]]["avg_discount_pct"].mean()
        disc_delta_pp = round(d_l - d_p, 1)
        m_l  = base[base["year"].astype(str)==all_years_sorted[-1]]["avg_marketing_spend"].mean()
        m_p  = base[base["year"].astype(str)==all_years_sorted[-2]]["avg_marketing_spend"].mean()
        if m_p: mktg_pct = round((m_l - m_p) / m_p * 100, 1)

    pk1, pk2, pk3, pk4 = st.columns(4)
    pk1.metric("Avg Discount Depth",    f"{avg_disc:.1f}%")
    pk2.metric(
        "Discount Change (YoY)",
        f"{disc_delta_pp:+.1f}pp" if disc_delta_pp is not None else "—",
        delta=f"{disc_delta_pp:.1f}pp" if disc_delta_pp is not None else None,
        delta_color="inverse",
    )
    pk3.metric("Avg Monthly Mktg Spend", f"${avg_mktg:,.0f}")
    pk4.metric(
        "Mktg Spend Growth (YoY)",
        f"{mktg_pct:+.1f}%" if mktg_pct is not None else "—",
        delta=f"{mktg_pct:.1f}%" if mktg_pct is not None else None,
        delta_color="normal",
    )

    st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

    # ── Promo breakdown table (by category, latest year) ─────────────────────
    latest_yr = all_years_sorted[-1]
    prior_yr  = all_years_sorted[-2] if len(all_years_sorted) >= 2 else None

    promo_base = cat_yr_full[cat_yr_full["category"].isin(cat_filter)]
    latest_promo = promo_base[promo_base["year"].astype(str) == latest_yr].set_index("category")
    prior_promo  = (promo_base[promo_base["year"].astype(str) == prior_yr].set_index("category")
                    if prior_yr else None)

    promo_rows = []
    for cat in sorted(cat_filter):
        if cat not in latest_promo.index:
            continue
        row = latest_promo.loc[cat]
        disc    = row["avg_discount_pct"]
        mktg    = row["avg_marketing_spend"]
        rev     = row["total_revenue"]
        eff     = rev / mktg if mktg else 0

        disc_chg = "—"
        mktg_chg = "—"
        if prior_promo is not None and cat in prior_promo.index:
            p = prior_promo.loc[cat]
            d_chg = disc - p["avg_discount_pct"]
            disc_chg = f"{d_chg:+.1f}pp"
            if p["avg_marketing_spend"]:
                m_chg = (mktg - p["avg_marketing_spend"]) / p["avg_marketing_spend"] * 100
                mktg_chg = f"+{m_chg:.1f}%" if m_chg >= 0 else f"{m_chg:.1f}%"

        promo_rows.append([
            cat,
            f"{disc:.1f}%",
            disc_chg,
            f"${mktg:,.0f}/mo",
            mktg_chg,
            f"{eff:.1f}x",
        ])

    render_table(
        f"Promo & Marketing by Category  ({latest_yr}  vs  {prior_yr or '—'})",
        ["Category", "Avg Discount", "vs Prior Year", "Mktg Spend", "vs Prior Year", "Rev / Mktg $"],
        promo_rows,
    )

    # ── ONE chart: efficiency bars ────────────────────────────────────────────
    eff_data = []
    for cat in cat_filter:
        if cat not in latest_promo.index: continue
        r = latest_promo.loc[cat]
        m = r["avg_marketing_spend"]
        eff_data.append({"Category": cat, "Efficiency": round(r["total_revenue"] / m if m else 0, 1)})
    eff_df = pd.DataFrame(eff_data).sort_values("Efficiency", ascending=True)

    if not eff_df.empty:
        fig = go.Figure(go.Bar(
            y=eff_df["Category"], x=eff_df["Efficiency"],
            orientation="h",
            marker=dict(color=CAT_COLORS[:len(eff_df)], opacity=0.88),
            text=[f"  {v:.1f}x" for v in eff_df["Efficiency"]],
            textposition="outside",
            textfont=dict(size=12, color="#0F172A"),
            hovertemplate="<b>%{y}</b><br>%{x:.1f}x revenue per $ spent<extra></extra>",
            width=0.5,
        ))
        styled(fig, f"Revenue per $ of Marketing Spend  ({latest_yr})", height=260)
        fig.update_xaxes(title_text="Revenue / Marketing Spend (×)")
        fig.update_layout(margin=dict(r=80))
        st.plotly_chart(fig, use_container_width=True, config=CHART_CFG)
