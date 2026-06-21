# Build Progress

## Done
- [x] Repo: `git init` + GitHub remote at https://github.com/Sameerna/cpg-sales-analytics
- [x] 9 raw CSVs in `data/raw/` — 42k transactions, 3 yrs (2022-2024), rich business patterns
- [x] `ingestion/load_raw.py` — loads all CSVs into SQLite raw_* tables
- [x] `ingestion/validate.py` — cleans to clean_* tables, 4,271 rows quarantined in rejected_records
- [x] `requirements.txt` + `.env.example`

## Next (in order)
- [x] dbt_project/ — stg_* staging models + mart_* aggregation models (8 models, 35 tests — all pass)
- [x] ml/train.py + ml/predict.py — Ridge regression + MLflow (R²=0.785, MAE=$2,043)
- [x] api/main.py + routes — FastAPI (predict, insights via Claude, metrics, summary)
- [x] api/llm.py — Claude Opus 4.8 with adaptive thinking + streaming; privacy-safe (only pre-aggregated metrics sent to API)
- [x] dashboard/app.py — Streamlit UI (4 tabs: KPIs, trends, forecast, AI insights)
- [x] Two-tab answer UX: ⚡ Executive Summary (fast, question-specific narrative) + ✦ Deep Think (Claude streaming)
- [x] Executive Summary: elevated pitch paragraph + Supporting Evidence expander + Source Tables expander
- [x] Loading spinner on question submit (no grey flash)
- [ ] tests/ — pytest
- [ ] Dockerfile + docker-compose.yml + Makefile
- [ ] .github/workflows/ci.yml
- [ ] docs/adr/ADR-001 + ADR-002
- [ ] Push to GitHub

## Key facts
- Python 3.9 — use `python3`, `pip3`, `Optional[str]` not `str | None`
- SQLite db: `./data/cpg.db`
- `make ingest` = `python3 ingestion/load_raw.py && python3 ingestion/validate.py`
- dbt binary: `/Users/as-mac-1392/Library/Python/3.9/bin/dbt`
- `make dbt` = `dbt run --project-dir dbt_project --profiles-dir dbt_project`
- Business questions the data answers: see README.md (refined section below)

## Business Questions (refined — no economic_indicators)
1. Did the Jan 2023 price hike hurt volume in elastic categories (Beverages, Snacks)?
2. Is RivalCo hurting us in East — and spreading to South?
3. Which promotions deliver the best volume lift vs margin trade-off?
4. Does summer heat actually drive Beverages revenue?
5. Is digital marketing spend converting to online channel growth?
6. Why is revenue up 74% over 2 years but market share is falling?
7. Are Tier A stores growing faster or slower than Tier C?
8. What % of revenue comes from repeat customers vs guest/new?
9. How much revenue did Q4 2023 stockouts cost us?
10. Which 2023-2024 new product launches are ramping above baseline?
