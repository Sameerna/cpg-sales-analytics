# CPG Revenue Intelligence Platform
### Built with Claude Code — AIA Engineer Evaluation Project

**Live:** [https://cpg-sales-analytics.streamlit.app/](https://cpg-sales-analytics.streamlit.app/)
**Repo:** [https://github.com/Sameerna/cpg-sales-analytics](https://github.com/Sameerna/cpg-sales-analytics)

---

## What This Is

A mid-size CPG company wants to understand their sales performance across categories and regions. They have 3 years of historical transaction data and a set of unanswered business questions. This platform gives them a clean data pipeline, a revenue forecast model, and a natural language interface — all in one deployable system.

---

## Business Questions the Platform Answers

| Question | What the data shows |
|---|---|
| Revenue is up 74% — why is market share falling? | The total market grew ~50% faster; a new competitor captured the incremental growth |
| Is there a new competitor? | RivalCo entered Beverages and Snacks in East region, Q3 2023 — documented in competitor_activity |
| How effective are our promotions? | Sharply varies: Beverages 1.45× uplift, Dairy only 1.12×, Snacks best overall ROI |
| Which region is weakening? | East declining post-Q3 2023 due to RivalCo entry; North resilient |
| Did the 2025 price hike hurt Beverages volume? | No — volume grew +20.8% YoY despite a +0.4% price increase; competitors responded with cuts, confirming our pricing had market power |
| Why is online growing but total share still dipping? | Online growing 25%/yr but the company is brick-and-mortar heavy; digital scale hasn't offset physical share loss |
| Which category is most at risk? | Beverages: price-elastic, competitor-targeted, and demand is increasingly online-skewed |
| What's our Q4 revenue forecast? | Strong seasonal pattern ($75k Jan → $250k Dec); ML model forecasts by category × region × month |

---

## Dataset

Nine source files covering 3 years (2022–2025) across 5 product categories and 4 regions:

| File | Rows | What it enables |
|---|---|---|
| `transactions.csv` | 42,538 | Core revenue, channel, customer, seasonality |
| `products.csv` | 405 | SKU / category / subcategory, new launches |
| `stores.csv` | 60 | Tier A/B/C, footfall, online delivery flag |
| `promotions.csv` | 850 | Promo windows, channel-specific discounts |
| `market_data.csv` | 240 | Market share = company revenue ÷ total market |
| `weather_data.csv` | 144 | Weather → Beverages and Dairy demand signal |
| `marketing_spend.csv` | 540 | Marketing ROI, digital vs TV vs in-store |
| `stockout_events.csv` | 40 | Lost revenue during stockout periods |
| `competitor_activity.csv` | 17 | RivalCo / ValueBrand / HealthFirst events |

Realistic data-quality issues (nulls, inconsistent formats) are handled in `ingestion/validate.py` — 4,271 rows quarantined to `rejected_records`, not silently dropped.

---

## Architecture

```
data/raw/*.csv
      │
      ▼
ingestion/               load_raw.py  → raw_* tables
                         validate.py  → clean_* tables + rejected_records
      │
      ▼
dbt_project/             8 models → mart_* tables (35 dbt tests)
      │
      ├──▶ ml/            Ridge regression  R²=0.785  MAE≈$2,043
      │    train.py  →  ml/models/model.pkl
      │    predict.py (inference wrapper)
      │
      └──▶ api/            FastAPI
               ├── GET  /metrics           Portfolio KPIs
               ├── GET  /data/summary      Monthly & category breakdowns
               ├── POST /predict           ML revenue forecast
               ├── POST /insights          Local SQL analytics engine
               ├── POST /insights/exec     Structured executive brief
               ├── POST /insights/exec-ai  Claude 4–5 sentence paragraph (streaming)
               └── POST /insights/stream   Claude deep analysis (streaming)
                        │
                        ▼
               dashboard/app.py    Streamlit — KPI, Revenue, Promo tabs + Ask the Data
```

---

## ML Model — Ridge Regression

**The problem:** Given a category (e.g. Beverages), a region (e.g. North), and a month — what revenue should we expect? That is a regression problem: predict a number from structured inputs.

**Why Ridge, not a neural network or gradient boosting:**
- Only 720 training rows (1 month × 5 categories × 4 regions × 3 years) — a neural network would overfit immediately
- The relationships are linear: more marketing spend → more revenue; higher summer temperature → more Beverage sales
- Ridge is fast, explainable, and testable — exactly what the brief asks for
- GBM was tested; it gave no measurable R² improvement at 6× the training time

**The 9 features:**

| Feature | Type | What it captures |
|---|---|---|
| category | One-hot (5 values) | Beverages, Snacks, Dairy, Household, Personal Care |
| region | One-hot (4 values) | NA, LATAM, APAC, EMEA |
| month_num | Numeric | Seasonality signal |
| year_num | Numeric | Year-on-year growth trend |
| avg_temp_celsius | Numeric | Does heat drive Beverage sales? |
| rainfall_mm | Numeric | Weather demand signal |
| marketing_spend_usd | Numeric | Does spend convert to revenue? |
| active_promos | Numeric | Number of active promotions |
| avg_discount_pct | Numeric | Average discount depth |

**Results (80/20 train/test split, 576 training rows):**

| Metric | Value | What it means |
|---|---|---|
| R² = 0.785 | 79% | The model explains 79% of why revenue varies month to month |
| MAE = $2,043 | ~15–20% error | On revenues of $5k–$15k per row — reasonable for a simple model |

---

## Data Privacy Architecture

The platform sends zero raw records to Claude. Before any Claude call, `_build_sanitised_context()` runs:

| Layer | What runs | Where it runs |
|---|---|---|
| Data retrieval | SQLite query | Your machine only |
| Aggregation | Python computes % growth, rankings, indexed values | Your machine only |
| What Claude sees | e.g. "Beverages: +12% YoY, rank 1/5" — no dollar amounts | Anthropic API |
| What Claude never sees | Transaction rows, store revenue, raw figures | Never leaves your environment |

Absolute revenue is replaced with:
- YoY % change (direction and magnitude, not amount)
- Rank among peers (e.g. rank 2 of 5 categories)
- Indexed values (marketing spend normalised to 100 = peak)

Setting `USE_LLM=false` in `.env` skips the Claude call entirely — the aggregated statistics are still returned, nothing leaves your network.

---

## How It Was Built — Iteration by Iteration

The platform was built through a conversation-driven process using Claude Code. Every feature came from a real request or a problem spotted in the browser.

**Iteration 1 — Data pipeline + API + basic dashboard**
Ingested 9 CSVs, built 8 dbt transformation models with 35 tests, trained the Ridge regression model, and exposed a FastAPI layer. The Streamlit dashboard showed KPI cards and charts. Functional — but silent. It could not answer a question.

**Iteration 2 — LLM integration**
- Upgraded to Claude Opus 4.8 with adaptive thinking and streaming
- Wrote `api/llm.py` from scratch with `_build_sanitised_context()` — strips all raw revenue before anything reaches Claude. Privacy constraint set here and never relaxed.
- Added `POST /insights/stream` returning a `StreamingResponse`

**Iteration 3 — "Two tabs per question: Executive Summary and Deep Think"**
The single answer box was replaced with a two-tab design:
- **⚡ Executive Summary** — fast, SQL-computed, loads in under 2 seconds
- **✦ Deep Think** — Claude streaming token by token

**Iteration 4 — "This is a numbers dump. We're talking to C-suite."**
The original Executive Summary was a bullet list of every metric — formatted like a data export, not a boardroom brief.

Complete redesign: `_compute_exec_brief()` returns `{narrative, evidence, sources}`. The narrative is 3–4 sentences that directly answer the question asked, with expandable Supporting Evidence tables and full Source Table attribution so any claim can be traced back to its origin.

**Iteration 5 — "The summary is the same for every question"**
`_synthesise_paragraph()` added keyword intent detection — each question now routes to a different data slice:
- Regional questions → underperforming region gap analysis
- Category questions → momentum ranking with ROI comparison
- Marketing questions → channel mix and per-category efficiency
- Risk questions → stockout cluster analysis with loss attribution
- Price elasticity questions → Beverages YoY volume vs price delta with competitor response

**Iteration 6 — Two-part Executive Summary**
Clear separation of concerns within the Executive Summary:
- **📊 Data Intelligence** (green) — computed from row-level data, no data leaves your environment
- **✦ AI Synthesis** (blue) — Claude's 4–5 sentence executive paragraph, grounded in pre-aggregated statistics only

A viewer knows exactly what is machine-computed fact versus AI-generated narrative.

**Iteration 7 — UI polish**
- Fixed macOS dark mode making AI text invisible: `.streamlit/config.toml` forces light theme
- Fixed Claude using "North/South" instead of "EMEA/APAC": applied `_RMAP` in `_build_sanitised_context()`
- Fixed blank grey screen on question submit: `st.empty()` loading card renders as the first delta
- Custom typed questions route to Deep Think first; chip clicks route to Executive Summary first

---

## Tech Stack

| Layer | Technology |
|---|---|
| Storage | SQLite (single file, zero config) |
| Transformation | dbt-core 1.8 + dbt-sqlite, 8 models, 35 tests |
| ML | scikit-learn Ridge regression, MLflow tracking |
| API | FastAPI, Pydantic, Uvicorn |
| LLM | Claude Opus 4.8, adaptive thinking, streaming |
| Dashboard | Streamlit, Plotly |
| CI/CD | GitHub Actions: seed → dbt → train → pytest → Docker build |
| Containerisation | Docker, docker-compose |
| Deployment | Render (API) + Streamlit Community Cloud (dashboard) |

---

## Production Readiness

- **17 tests passing** across 3 test files: ingestion quality, ML model, API integration
- **Dockerfile + docker-compose** — `docker compose up` starts both services
- **GitHub Actions CI** — every push runs the full pipeline: seed DB → dbt → train → pytest → docker build
- **2 Architecture Decision Records** (ADR-001: SQLite vs warehouse; ADR-002: dbt over raw SQL)
- **Live deployment** — API on Render, dashboard on Streamlit Cloud, UptimeRobot pings `/health` every 5 minutes to keep Render awake

---

## Live Screenshots

*[Dashboard overview — KPI tab]*

*[Ask the Data — Executive Summary: Data Intelligence + AI Synthesis]*

*[Ask the Data — Deep Think streaming]*

*[Ask the Data — "Did the 2025 price hike hurt Beverages volume?"]*
