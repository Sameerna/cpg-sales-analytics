"""
Tests for the ingestion and data validation pipeline.
Verifies that raw CSVs load correctly and clean_* tables meet quality thresholds.
"""
import sqlite3
import pytest

DB = "./data/cpg.db"


@pytest.fixture(scope="module")
def con():
    conn = sqlite3.connect(DB)
    yield conn
    conn.close()


def tables(con):
    rows = con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r[0] for r in rows}


class TestRawTables:
    def test_raw_tables_exist(self, con):
        required = {
            "raw_transactions", "raw_marketing_spend",
            "raw_stockout_events", "raw_competitor_activity",
        }
        assert required.issubset(tables(con)), "One or more raw_* tables missing"

    def test_raw_transactions_has_rows(self, con):
        count = con.execute("SELECT COUNT(*) FROM raw_transactions").fetchone()[0]
        assert count > 10_000, f"Expected >10k transaction rows, got {count}"


class TestCleanTables:
    def test_clean_tables_exist(self, con):
        required = {
            "clean_transactions", "clean_marketing_spend",
            "clean_stockout_events", "clean_competitor_activity",
        }
        assert required.issubset(tables(con)), "One or more clean_* tables missing"

    def test_no_null_price_or_quantity(self, con):
        nulls = con.execute(
            "SELECT COUNT(*) FROM clean_transactions "
            "WHERE unit_price IS NULL OR quantity IS NULL"
        ).fetchone()[0]
        assert nulls == 0, f"{nulls} rows with NULL price/quantity in clean layer"

    def test_no_negative_price(self, con):
        neg = con.execute(
            "SELECT COUNT(*) FROM clean_transactions WHERE unit_price < 0"
        ).fetchone()[0]
        assert neg == 0, f"{neg} rows with negative unit_price"

    def test_rejected_records_table_exists(self, con):
        assert "rejected_records" in tables(con)

    def test_quarantine_rate_reasonable(self, con):
        raw      = con.execute("SELECT COUNT(*) FROM raw_transactions").fetchone()[0]
        rejected = con.execute("SELECT COUNT(*) FROM rejected_records").fetchone()[0]
        rate = rejected / raw if raw else 1
        assert rate < 0.20, f"Quarantine rate {rate:.1%} exceeds 20% — check validate.py"

    def test_clean_transactions_row_count(self, con):
        count = con.execute("SELECT COUNT(*) FROM clean_transactions").fetchone()[0]
        assert count > 50_000, f"Expected >50k clean rows, got {count}"


class TestMartTables:
    def test_mart_tables_exist(self, con):
        required = {
            "mart_forecast_inputs", "mart_revenue_by_region",
            "mart_revenue_by_category",
        }
        assert required.issubset(tables(con)), "One or more mart_* tables missing"

    def test_mart_forecast_inputs_has_rows(self, con):
        count = con.execute("SELECT COUNT(*) FROM mart_forecast_inputs").fetchone()[0]
        assert count > 0, "mart_forecast_inputs is empty"

    def test_categories_present(self, con):
        cats = {
            r[0] for r in con.execute(
                "SELECT DISTINCT category FROM mart_forecast_inputs"
            ).fetchall()
        }
        expected = {"Beverages", "Snacks", "Dairy", "Personal Care", "Household"}
        assert expected.issubset(cats), f"Missing categories: {expected - cats}"

    def test_mart_revenue_by_region_has_all_regions(self, con):
        regions = {
            r[0] for r in con.execute(
                "SELECT DISTINCT region FROM mart_revenue_by_region"
            ).fetchall()
        }
        assert len(regions) >= 4, f"Expected ≥4 regions, got {regions}"
