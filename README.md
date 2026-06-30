# CPG Revenue Intelligence Platform

**Live demo: [https://cpg-sales-analytics.streamlit.app/](https://cpg-sales-analytics.streamlit.app/)**


If you see an error like "uvicorn api.main:app --reload", please reach out to sameernajoshi@gmail.com, since this is a free version the systems can be down due to inactivity, I will need to spin it back up. 

A full-stack analytics platform for Consumer Packaged Goods sales data — combining a production-grade data pipeline, a machine learning forecast engine, and a Claude-powered AI layer that answers business questions in plain language.

![Python](https://img.shields.io/badge/Python-3.9-blue?style=flat-square&logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?style=flat-square&logo=fastapi)
![Streamlit](https://img.shields.io/badge/Streamlit-1.35-FF4B4B?style=flat-square&logo=streamlit)
![dbt](https://img.shields.io/badge/dbt-1.8-orange?style=flat-square&logo=dbt)
![Claude](https://img.shields.io/badge/Claude-Opus_4.8-8A2BE2?style=flat-square)
![CI](https://img.shields.io/github/actions/workflow/status/Sameerna/cpg-sales-analytics/ci.yml?style=flat-square&label=CI)

---

## What it does

Ask a natural language question about the portfolio — *"Which regions are underperforming?"* or *"What does marketing efficiency tell us?"* — and the platform responds with two answers simultaneously:

- **Data Intelligence** — computed directly from row-level transaction data using SQL and ML, with no data leaving your environment
- **AI Synthesis** — a 4–5 sentence executive narrative written by Claude, grounded in pre-aggregated statistics only (raw records are never forwarded)

The dashboard also provides KPI cards, revenue trends, promotion analysis, and a Ridge regression model that forecasts next-period revenue by category and region.

---

## Architecture

```
data/raw/*.csv
      │
      ▼
ingestion/              # load_raw.py → raw_* tables
      │                 # validate.py → clean_* tables + rejected_records
      ▼
dbt_project/            # 8 dbt models → mart_* tables (27 schema tests)
      │
      ├──▶ ml/          # Ridge regression (R²=0.785, MAE≈$2,043)
      │    # Ridge chosen over tree methods: mart features are linear combinations
      │    # of monthly aggregates; GBM gave no measurable R² improvement at 6× training time
      │    train.py → ml/models/model.pkl
      │    predict.py
      │
      └──▶ api/          # FastAPI
               │
               ├── /metrics          GET  portfolio KPIs
               ├── /data/summary     GET  monthly & category summaries
               ├── /predict          POST ML revenue forecast
               ├── /insights         POST local SQL analytics engine
               ├── /insights/exec    POST structured executive brief
               ├── /insights/exec-ai POST Claude short paragraph (streaming)
               └── /insights/stream  POST Claude deep analysis (streaming)
                        │
                        ▼
               dashboard/app.py      # Streamlit — 3 analytics tabs + Ask the Data
```

**Privacy guarantee:** `_build_sanitised_context()` strips all absolute revenue figures before any data reaches Claude. Only growth rates, rankings, and indexed values are forwarded.

---

## Quick start

### Local (recommended for development)

**Requires Python 3.9 – 3.12.**

```bash
# 1. Clone and create a virtual environment
git clone https://github.com/Sameerna/cpg-sales-analytics.git
cd cpg-sales-analytics
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Open .env — the defaults work out of the box (USE_LLM=false)
# To enable AI features, set USE_LLM=true and add your ANTHROPIC_API_KEY

# 4. Build the database and ML model  (~30 seconds)
make setup          # ingest → dbt → train

# 5. Start the API (Terminal 1 — keep venv active)
make api

# 6. Start the dashboard (Terminal 2 — keep venv active)
make dashboard
# Open http://localhost:8501
```

> **No API key needed to get started.** The default `USE_LLM=false` runs
> entirely offline — all KPI charts, revenue tables, ML forecasts, and the
> Data Intelligence answers work without Claude. Set `USE_LLM=true` in `.env`
> and add an `ANTHROPIC_API_KEY` to unlock the AI Synthesis and Deep Think tabs.

### Docker

```bash
cp .env.example .env   # defaults work; add API key to enable AI features
docker compose up -d
# API:       http://localhost:8000
# Dashboard: http://localhost:8501
```

---

## Live deployment (Render API + Streamlit Cloud)

Deploy a permanent public URL in three steps — no server management, API key stays private.

### Step 1 — Deploy the API to Render

1. Go to [render.com](https://render.com) → **New** → **Web Service**
2. Connect your GitHub repo (`cpg-sales-analytics`)
3. Render detects `render.yaml` automatically — click **Apply**
4. In the Render dashboard → **Environment** → add one secret variable:
   ```
   ANTHROPIC_API_KEY = sk-ant-...   ← your real key, never goes in code
   ```
5. Click **Deploy** — build takes ~3 minutes (installs deps, runs pipeline, trains model)
6. Copy your service URL: `https://cpg-analytics-api.onrender.com`

### Step 2 — Keep Render awake (free, 2-week guarantee)

Render free tier sleeps after 15 min of inactivity. Fix with **UptimeRobot**:

1. Go to [uptimerobot.com](https://uptimerobot.com) → **Add New Monitor**
2. Type: **HTTP(s)**
3. URL: `https://cpg-analytics-api.onrender.com/health`
4. Interval: **5 minutes**
5. Click **Create Monitor**

That's it — UptimeRobot pings every 5 minutes, Render never sleeps.

### Step 3 — Deploy the dashboard to Streamlit Community Cloud

1. Go to [share.streamlit.io](https://share.streamlit.io) → **New app**
2. Connect your GitHub repo, set **Main file path**: `dashboard/app.py`
3. Click **Advanced settings → Secrets** and paste:
   ```toml
   API_BASE = "https://cpg-analytics-api.onrender.com"
   API_KEY  = "cpg-live-key"
   ```
   *(see `.streamlit/secrets.toml.example` for reference)*
4. Click **Deploy** — done in ~60 seconds
5. Share the URL: `https://your-app.streamlit.app`

Visitors get the full dashboard. Your API key is stored in Render's vault — never visible to anyone accessing the URL.

---

## Make targets

| Command | What it does |
|---|---|
| `make setup` | Full pipeline: install → ingest → dbt → train |
| `make api` | Start FastAPI with hot-reload |
| `make dashboard` | Start Streamlit dashboard |
| `make test` | Run ingestion + model tests (17 tests) |
| `make test-all` | Run all tests including API tests |
| `make lint` | Run ruff linter |
| `make docker-build` | Build Docker image |
| `make docker-up` | Start both services via docker-compose |
| `make docker-down` | Stop services |

---

## Project structure

```
├── ingestion/
│   ├── load_raw.py          # CSV → raw_* SQLite tables
│   └── validate.py          # clean_* tables + quarantine
├── dbt_project/
│   └── models/
│       ├── staging/         # stg_* light transforms
│       └── marts/           # mart_forecast_inputs, mart_revenue_*
├── ml/
│   ├── train.py             # Ridge regression + MLflow logging
│   ├── predict.py           # Inference wrapper
│   └── models/model.pkl     # Trained artefact
├── api/
│   ├── main.py              # FastAPI app + auth middleware
│   ├── llm.py               # Claude API wrapper (streaming)
│   └── routes/
│       ├── metrics.py       # KPI aggregations
│       ├── data.py          # Monthly/category summaries
│       ├── predict.py       # ML forecast endpoint
│       └── insights.py      # AI insights (local + Claude)
├── dashboard/
│   └── app.py               # Streamlit UI
├── tests/
│   ├── test_ingestion.py    # 12 pipeline quality tests
│   ├── test_model.py        # 5 ML model tests
│   └── test_api.py          # 12 API integration tests
├── docs/
│   ├── ai-collaboration.md  # How this platform was built, request by request
│   ├── test-results.md      # Test run results and issue log
│   └── adr/
│       ├── ADR-001-sqlite-vs-warehouse.md
│       └── ADR-002-dbt-over-raw-sql.md
├── .streamlit/config.toml   # Forces light theme
├── .github/workflows/ci.yml # CI: test → docker build
├── Dockerfile
├── docker-compose.yml
└── Makefile
```

---

## API reference

All endpoints require the header `X-API-Key: <your-key>` (set `API_KEY` in `.env`).

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/metrics` | KPI summary — revenue, regions, categories |
| GET | `/data/summary` | Monthly and category breakdowns |
| POST | `/predict` | ML revenue forecast for a category/region/month |
| POST | `/insights` | Local SQL analytics (always available, `force_local` flag) |
| POST | `/insights/exec` | Structured executive brief — narrative + evidence + sources |
| POST | `/insights/exec-ai` | Streaming 4–5 sentence Claude paragraph |
| POST | `/insights/stream` | Streaming full Claude deep analysis |

Interactive docs: `http://localhost:8000/docs`

---

## Data

Nine CSV sources covering 3 years (2022–2024) across 5 product categories
and 4 regions:

| Source | Records | Description |
|---|---|---|
| `transactions` | 64,838 raw / 60,646 clean | SKU-level sales with channel, price, quantity |
| `marketing_spend` | 780 | Monthly spend by channel with impressions |
| `stockout_events` | 54 | Supply disruptions with duration and estimated lost revenue |
| `competitor_activity` | 17 | Competitor pricing moves, market entries, promotions |
| `market_data` | 340 | Total addressable market by category for share calculations |
| `products` / `stores` / `promotions` / `weather_data` | — | Enrichment tables |

---

## Tech stack

| Layer | Technology |
|---|---|
| Storage | SQLite (single file, zero config) |
| Transformation | dbt-core 1.8 + dbt-sqlite |
| ML | scikit-learn Ridge regression, MLflow tracking |
| API | FastAPI, Pydantic, Uvicorn |
| LLM | Anthropic Claude Opus 4.8, adaptive thinking, streaming |
| Dashboard | Streamlit, Plotly |
| CI | GitHub Actions |
| Containerisation | Docker, docker-compose |

**Incremental ingestion:** monthly transaction drops are handled automatically — place a new `transactions_YYYY_MM.csv` in `data/incoming/` and run `python ingestion/ingest_monthly.py`. The pipeline skips already-processed files (idempotent watermark log), validates and quarantines bad rows, appends clean data, and triggers a `dbt run` to refresh all marts.
