# ADR-002 — dbt over Raw SQL Scripts

**Date:** 2026-06-16
**Status:** Accepted

---

## Context

The platform needs to transform raw ingested data into analytics-ready mart
tables. Two approaches were considered for managing this transformation layer:

| Option | Description |
|---|---|
| **Raw SQL scripts** | Plain `.sql` files executed via `sqlite3` or a Python runner |
| **dbt** | SQL-first transformation framework with models, tests, and lineage |

---

## Decision

Use **dbt-core** with the `dbt-sqlite` adapter for all transformations
from `clean_*` → `mart_*` tables.

---

## Reasons

1. **Lineage is first-class** — dbt builds a DAG of model dependencies
   automatically. The `mart_forecast_inputs` model's upstream sources
   (`clean_transactions`, `clean_marketing_spend`, `clean_weather_data`, etc.)
   are explicit and visualisable with `dbt docs generate`.

2. **Built-in tests** — dbt's schema tests (`not_null`, `unique`,
   `accepted_values`, `relationships`) run with a single `dbt test` command.
   35 tests cover the mart layer, catching data quality regressions
   immediately.

3. **Reproducibility** — `dbt run` is idempotent. The mart tables can be
   rebuilt from scratch at any time, making CI straightforward: seed → dbt run
   → test.

4. **Documentation** — model descriptions in `schema.yml` generate a browsable
   data dictionary, making the transformation logic legible to non-engineers.

5. **Industry standard** — dbt is the dominant transformation tool in modern
   data stacks. Using it here reflects production patterns accurately.

---

## Consequences

- **Added dependency** — `dbt-core` and `dbt-sqlite` add ~50 MB to the
  install. This is an acceptable trade-off given the benefits.

- **SQL dialect** — dbt-sqlite's SQL dialect has minor differences from
  standard SQL (e.g., limited window function support). All mart models were
  written and tested against SQLite specifically.

- **Port path** — switching to a production warehouse (PostgreSQL, BigQuery)
  requires only swapping the dbt adapter and profile. The model SQL itself
  is portable.
