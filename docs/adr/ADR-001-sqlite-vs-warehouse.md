# ADR-001 — SQLite over a Cloud Data Warehouse

**Date:** 2026-06-16
**Status:** Accepted

---

## Context

The platform ingests ~65,000 transactions across 9 CSV sources covering
3 years of CPG sales data. A storage and query layer was needed that could
support ad-hoc SQL, dbt transformations, and ML feature extraction without
requiring external services or network connectivity.

The options considered were:

| Option | Pros | Cons |
|---|---|---|
| **SQLite** | Zero-config, file-based, ships with Python, runs offline | Not suitable for concurrent writes at scale |
| **DuckDB** | Columnar, fast analytics, also file-based | Less tooling support in dbt-sqlite ecosystem at the time |
| **PostgreSQL** | Production-grade, concurrent | Requires a running server, complicates local setup and CI |
| **BigQuery / Snowflake** | Scales to petabytes | Paid service, network dependency, overkill for <100k rows |

---

## Decision

Use **SQLite** via the `dbt-sqlite` adapter.

---

## Reasons

1. **Dataset fits comfortably** — 65k rows with 9 tables is well within SQLite's
   practical limits (SQLite handles databases up to 281 TB).

2. **Zero infrastructure** — no server to start, no credentials to manage, no
   cloud costs. The entire database is a single file (`data/cpg.db`) that can
   be committed or transferred trivially.

3. **CI simplicity** — GitHub Actions can seed the database in seconds with a
   plain `python3 ingestion/load_raw.py` step, no Docker service containers
   required for the database itself.

4. **dbt-sqlite support** — the `dbt-sqlite` adapter exposes the full dbt
   model/test/source layer against SQLite, enabling the same workflow as a
   production warehouse without the infrastructure.

5. **Portability** — anyone cloning the repo can run `make setup` and have a
   fully populated database in under 60 seconds on any OS.

---

## Consequences

- **Accepted limitation:** SQLite does not support concurrent writes. This is
  fine for this platform — ingestion runs once, and all subsequent access is
  read-only (API queries, ML training, dashboard).

- **Migration path:** If data volume grows to millions of rows or concurrent
  write ingestion is needed, the dbt models and SQL in `api/routes/` are
  standard SQL and will port to PostgreSQL or DuckDB with minimal changes
  (swap the dbt adapter and connection string).
