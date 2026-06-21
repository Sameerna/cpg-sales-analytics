# Test Results
### CPG Revenue Intelligence Platform

**Run date:** 2026-06-21
**Python:** 3.9.6
**pytest:** 8.4.2
**Platform:** macOS (darwin)

---

## Summary

| Suite | Tests | Passed | Failed | Duration |
|---|---|---|---|---|
| `test_ingestion.py` | 12 | 12 | 0 | ~1.5 s |
| `test_model.py` | 5 | 5 | 0 | ~0.2 s |
| `test_api.py` | 10 | — | — | requires live API |
| **Total (offline)** | **17** | **17** | **0** | **1.47 s** |

---

## test_ingestion.py — Data Pipeline Tests

Tests that the raw → clean → mart pipeline ran correctly and the data
meets quality standards.

### Raw Layer

| Test | What it checks | Result |
|---|---|---|
| `test_raw_tables_exist` | `raw_transactions`, `raw_marketing_spend`, `raw_stockout_events`, `raw_competitor_activity` all present | ✅ PASSED |
| `test_raw_transactions_has_rows` | `raw_transactions` contains > 10,000 rows (actual: 64,838) | ✅ PASSED |

### Clean Layer

| Test | What it checks | Result |
|---|---|---|
| `test_clean_tables_exist` | `clean_transactions`, `clean_marketing_spend`, `clean_stockout_events`, `clean_competitor_activity` all present | ✅ PASSED |
| `test_no_null_price_or_quantity` | Zero rows with NULL `unit_price` or `quantity` after validation | ✅ PASSED |
| `test_no_negative_price` | Zero rows with negative `unit_price` | ✅ PASSED |
| `test_rejected_records_table_exists` | Quarantine table `rejected_records` was created by `validate.py` | ✅ PASSED |
| `test_quarantine_rate_reasonable` | Rejected rows < 20% of raw (actual: 4,271 / 64,838 = 6.6%) | ✅ PASSED |
| `test_clean_transactions_row_count` | `clean_transactions` has > 50,000 rows (actual: 60,646) | ✅ PASSED |

### Mart Layer (dbt)

| Test | What it checks | Result |
|---|---|---|
| `test_mart_tables_exist` | `mart_forecast_inputs`, `mart_revenue_by_region`, `mart_revenue_by_category` all present | ✅ PASSED |
| `test_mart_forecast_inputs_has_rows` | `mart_forecast_inputs` is not empty (actual: 1,040 rows) | ✅ PASSED |
| `test_categories_present` | All 5 categories present: Beverages, Snacks, Dairy, Personal Care, Household | ✅ PASSED |
| `test_mart_revenue_by_region_has_all_regions` | ≥ 4 regions present in regional mart | ✅ PASSED |

---

## test_model.py — ML Model Tests

Tests the Ridge regression model artefact at `ml/models/model.pkl`.

| Test | What it checks | Result |
|---|---|---|
| `test_predict_function_callable` | `ml.predict.predict` imports and is callable | ✅ PASSED |
| `test_returns_dict_with_predicted_revenue` | Return value is a dict containing `predicted_revenue` key | ✅ PASSED |
| `test_prediction_is_positive` | Predictions are always > 0 for valid inputs | ✅ PASSED |
| `test_higher_marketing_spend_increases_prediction` | Increasing marketing spend ($5k → $50k) raises the forecast (confirms feature learned correctly) | ✅ PASSED |
| `test_all_categories_predict` | All 5 categories return a positive prediction without error | ✅ PASSED |

**Model stats (from training run):** R² = 0.785 · MAE ≈ $2,043 · Ridge regression

---

## test_api.py — API Integration Tests

These tests require the FastAPI server to be running (`uvicorn api.main:app`).
They are skipped gracefully in CI when the server is not reachable, and run
as a separate step in the GitHub Actions workflow with `USE_LLM=false`.

| Test | What it checks |
|---|---|
| `test_health_ok` | `GET /health` returns 200 |
| `test_unauthorized_rejected` | `GET /metrics` without API key returns 401 |
| `test_metrics_returns_200` | `GET /metrics` with key returns 200 |
| `test_metrics_has_regions` | Response contains `regions` array with at least one entry |
| `test_data_summary_returns_200` | `GET /data/summary` returns 200 |
| `test_data_summary_has_monthly` | Response contains `monthly` array |
| `test_local_insights_returns_200` | `POST /insights` with `force_local=true` returns 200 |
| `test_local_insights_has_insight_field` | Response has `insight` field and `llm_used: false` |
| `test_exec_brief_returns_200` | `POST /insights/exec` returns 200 |
| `test_exec_brief_structure` | Response has `narrative`, `evidence`, `sources` with non-empty narrative |
| `test_predict_returns_200` | `POST /predict` returns 200 |
| `test_predict_returns_positive_revenue` | `predicted_revenue` > 0 for valid inputs |

---

## Issues encountered and fixes

### 1 — Wrong table names assumed
Initial test scaffold used `raw_sales_transactions` and `clean_sales_transactions`.
Actual table names are `raw_transactions` and `clean_transactions` (shorter names
from the ingestion scripts). Fixed by inspecting the live database before finalising.

### 2 — `clean_transactions` has no `revenue` column
Revenue is not stored directly — it is computed as `quantity × unit_price` in the
mart layer. Tests updated to check `unit_price` and `quantity` instead.

Both issues were caught and fixed before the first push. Final run: **17/17 passed**.

---

## CI Pipeline

Tests run automatically on every push to `main` via `.github/workflows/ci.yml`:

```
push to main
  └── test job
        ├── seed DB (load_raw.py + validate.py)
        ├── dbt run
        ├── train ML model
        ├── pytest test_ingestion.py test_model.py
        ├── start uvicorn (USE_LLM=false)
        └── pytest test_api.py
  └── docker job (runs after test job passes)
        └── docker build
```
