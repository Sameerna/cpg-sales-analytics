# AI Collaboration Log
### CPG Revenue Intelligence Platform — Built with Claude Code

This document traces how the platform evolved through a conversation-driven
development process. Every feature below was shaped by a real request, a real
problem spotted in the browser, or a real design decision made together.

---

## Where it started

The project began as a data engineering exercise: ingest raw CSVs, clean them,
run dbt transformations, train a Ridge regression model, and expose a FastAPI
layer. The Streamlit dashboard showed KPI cards and charts. Functional — but
silent. It could not answer a question.

---

## The evolution, request by request

### 1 — "Let's integrate LLMs"
The first ask. At this point the `/insights` endpoint existed but called a
local SQL function and returned a text blob. The work here was significant:

- Upgraded to **Claude Opus 4.8** with adaptive thinking
- Wrote `api/llm.py` from scratch — streaming, error surfacing, privacy-safe
- Added `_build_sanitised_context()`: strips all raw revenue figures, sends
  only growth rates, rankings, and indexed values to Claude
- Wired a new `POST /insights/stream` endpoint with `StreamingResponse`

*Privacy constraint set here and never relaxed: Claude never sees row-level
data or absolute revenue totals.*

---

### 2 — "Two tabs for each question — Executive Summary and Deep Think"
The single answer box was replaced with a two-tab design:

- **⚡ Executive Summary** — fast, SQL-computed, always available
- **✦ Deep Think** — Claude streaming, token by token

The tab pattern meant users could get a quick answer in under 2 seconds while
the deep analysis loaded in the background.

---

### 3 — "The screen goes grey when I click a question"
Streamlit reruns blank the page before new content arrives. Fix: an
`st.empty()` loading card rendered as the *very first delta* on question
submit — a spinning indicator that disappears only once the API responds.
No more grey flash.

---

### 4 — "This is not a summary. It's a numbers dump. We're talking to C-suite."
The original Executive Summary was a bullet list of every metric in the
database — formatted like a data export, not a boardroom brief.

Complete redesign:
- `_compute_exec_brief()` replaces `_compute_data_insight()`
- Returns structured `{narrative, evidence, sources}` instead of a text blob
- **Narrative**: 3–4 sentences that directly answer the question asked
- **Supporting Evidence**: expandable tables (the numbers, when you want them)
- **Source Tables**: layered attribution — Clean → Mart → ML — so anyone can
  trace a claim back to its origin table

---

### 5 — "The summary is the same for every question"
The narrative paragraph was computing from all data regardless of what was
asked. Fixed with `_synthesise_paragraph()`: keyword intent detection routes
each question to its most relevant data slice.

- Regional questions → underperforming region gap analysis
- Category questions → momentum ranking with ROI comparison
- Marketing questions → channel mix and per-category efficiency
- Risk questions → stockout cluster analysis with loss attribution
- Investment questions → ML forecast + market share gainers
- Competitor questions → recent activity log with named players

*"Which regions are underperforming?" now gets a completely different answer
from "Which category has the strongest momentum?"*

---

### 6 — "Two parts in Executive Summary: Local Data and a Claude paragraph"
The Executive Summary gained a clear separation of concerns:

**📊 Data Intelligence** (green accent)
Numbers computed entirely from the local database using SQL and the Ridge
regression model. Row-level data is used here.
*"Computed from row-level transaction data using local ML models · No data
sent externally"*

**✦ AI Synthesis** (blue accent)
A new `POST /insights/exec-ai` endpoint with a tighter system prompt — asks
Claude for exactly 4–5 sentences of decisive prose, no bullet points.
*"Row-level data is not provided to Claude · AI-generated text based on
pre-aggregated statistics only"*

This separation was deliberate: it lets a viewer know exactly what is
machine-computed fact versus AI-generated narrative.

---

### 7 — "Custom questions should go straight to Deep Think"
Chip (suggested) questions default to Executive Summary — the answer is
pre-mapped and loads instantly. But a custom typed question is open-ended;
Deep Think is the right destination.

Implementation: `is_custom_q` session state flag flips tab order. When you
type a question, `✦ Deep Think` becomes the first (default) tab.

---

### 8 — "The colors are all black. Fix the consistency."
The root cause: macOS dark mode. Streamlit inherits the system color scheme,
turning chip buttons black, streaming text invisible (white on white), and
inputs dark.

Fix: `.streamlit/config.toml` with an explicit light theme — brand blue
`#2563EB`, background `#F8FAFC`, text `#0F172A`. The dashboard now renders
identically regardless of system theme.

---

### 9 — "Claude says North/South/East/West. I want EMEA, LATAM, APAC, NA."
The sanitised context sent to Claude used the raw database region codes
("North", "South", etc.). One-line fix: apply `_RMAP` in
`_build_sanitised_context()` so Claude receives and uses the same display
names as the rest of the dashboard.

---

## What this process looked like

Every change above started as a sentence — sometimes a screenshot, sometimes
a three-word message. Claude Code translated intent into working code:
reading the right files, making targeted edits, running syntax checks, and
committing with meaningful messages.

The git history is intentionally kept clean and descriptive so the
*reasoning* behind each change is legible — not just what changed, but why.

---

## Stack summary

| Layer | Technology |
|---|---|
| Data pipeline | Python 3.9, SQLite, dbt-core |
| ML model | scikit-learn Ridge regression, MLflow |
| API | FastAPI, Pydantic |
| LLM | Claude Opus 4.8, adaptive thinking, streaming |
| Dashboard | Streamlit, Plotly |
| Privacy | Pre-aggregated context only — no raw data to Claude |

---

*Built during a 2-week AI Acceleration Engineer evaluation at Sigmoid.*
*AI tooling: Claude Code (Anthropic) throughout.*
