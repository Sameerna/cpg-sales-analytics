# Extension Points

This skeleton is meant to be inherited and extended. The system is deliberately
layered so each concern has one obvious place to change. Below are the seams a
project team will most likely touch, in rough order of frequency.

The data flows in one direction, so changes propagate predictably:

```
data/raw/*.csv → ingestion → SQLite (raw_/clean_) → dbt (stg_/mart_) → ml + api → dashboard
```

---

## 1. Add a new data source (CSV feed)

**Where:** [`ingestion/load_raw.py`](../ingestion/load_raw.py) → [`ingestion/validate.py`](../ingestion/validate.py) → [`dbt_project/models/staging/sources.yml`](../dbt_project/models/staging/sources.yml)

1. Drop the CSV in `data/raw/`.
2. Register it in `load_raw.py` so it lands in a `raw_<name>` table.
3. Add validation/cleaning rules in `validate.py` to produce `clean_<name>`
   (reuse the existing `reject()` quarantine pattern for bad rows).
4. Declare the `clean_<name>` table as a dbt source in `sources.yml` so models
   can `{{ source('main', 'clean_<name>') }}` it.

**Contract:** keep the `raw_*` → `clean_*` → quarantine pattern. Anything a model
consumes should be a validated `clean_*` table, never a `raw_*` one.

---

## 2. Add or change a transformation / metric (dbt)

**Where:** [`dbt_project/models/`](../dbt_project/models/) (`staging/` for light renames/casts, `marts/` for business aggregates)

- New light transform → add a `stg_<name>.sql` view.
- New business metric → add a `mart_<name>.sql` table, then add tests in
  [`schema.yml`](../dbt_project/models/marts/schema.yml) (column-level) or a new
  file under [`tests/`](../dbt_project/tests/) (singular assertions).
- Run `make dbt && make dbt-test` to build and verify.

**Contract:** the ML model and the API read from the marts, not from raw tables.
If you change `mart_forecast_inputs`'s grain or columns, update §3 and §4 to match.

---

## 3. Swap or retrain the forecast model

**Where:** [`ml/train.py`](../ml/train.py) (training) and [`ml/predict.py`](../ml/predict.py) (inference)

- Features are declared once at the top of `train.py`
  (`NUMERIC_FEATURES` / `CATEGORICAL_FEATURES` / `TARGET`). Add a feature there
  and in `mart_forecast_inputs`.
- To swap the estimator, change `build_pipeline()` — the `ColumnTransformer`
  preprocessing is model-agnostic, so most estimators drop in with no other change.
- `predict.py` loads the pickled pipeline; keep its input-row schema in sync with
  the training features.
- MLflow logs params/metrics to `./mlruns` on every `make train`.

**Known next step (documented in the Decision Log):** the train/test split is a
random shuffle. For an honest time-series metric, switch to a temporal holdout
(train ≤ year N-1, test = year N) before trusting the reported R².

---

## 4. Add an API endpoint

**Where:** [`api/routes/`](../api/routes/) + register in [`api/main.py`](../api/main.py)

- Create a router module under `routes/`, define Pydantic request/response models,
  then `app.include_router(...)` in `main.py`.
- All routers are mounted behind `Depends(require_api_key)` — new endpoints inherit
  `X-API-Key` auth automatically.

---

## 5. Add a question type / intent (insights engine)

**Where:** [`api/routes/insights.py`](../api/routes/insights.py)

- The local analytics engine routes each question to a data slice via keyword
  intent detection in `_synthesise_paragraph()`. Add a new branch there for a new
  question category, with its own SQL slice.
- **Privacy contract:** anything sent to Claude must go through
  `_build_sanitised_context()`, which forwards only relative statistics (growth %,
  shares, rankings, indices) — never raw revenue. This invariant is guarded by
  [`tests/test_privacy.py`](../tests/test_privacy.py); keep it green.

---

## 6. Dashboard UI

**Where:** [`dashboard/app.py`](../dashboard/app.py)

- The dashboard is a thin client over the API — it renders KPI/metrics, the
  forecast form, and the "Ask the Data" tabs. Suggested-question chips and intent
  defaults live here. Theme is pinned in [`.streamlit/config.toml`](../.streamlit/config.toml).

---

## Incremental / production ingestion

[`ingestion/ingest_monthly.py`](../ingestion/ingest_monthly.py) handles recurring
monthly transaction drops idempotently: place `transactions_YYYY_MM.csv` in
`data/incoming/`, run the script, and it validates, quarantines bad rows, appends
clean data (skipping already-processed files via a watermark log), and triggers a
`dbt run`. This is the intended hook for scheduling (cron / Airflow / a managed
orchestrator) when this moves to production.

---

## Testing & CI

- `make test` — ingestion + model + privacy tests.
- `make test-all` — adds API integration tests.
- `make dbt-test` — dbt schema + singular data-quality assertions.
- `make lint` — ruff (policy in [`ruff.toml`](../ruff.toml)).
- CI ([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)) runs lint → seed →
  dbt run → dbt test → train → tests → API tests → Docker build on every push/PR.
  Add new test files to the pytest invocation there so they gate merges.
