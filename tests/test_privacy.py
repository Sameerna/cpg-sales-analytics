"""
Privacy regression test.

The README's central claim is that raw revenue never reaches Claude — only
relative statistics (growth %, shares, rankings, indices) are forwarded. This
test guards that invariant against the actual sanitised context the LLM layer
builds, so a future refactor of `_build_sanitised_context()` can't silently
start leaking absolute figures.

Skips cleanly if the database hasn't been built yet (the pipeline must run
first), matching the style of the other suites.
"""
import os
import re
import sqlite3

import pytest

DB_PATH = os.getenv("DB_PATH", "./data/cpg.db")


@pytest.fixture(scope="module")
def context() -> str:
    if not os.path.exists(DB_PATH):
        pytest.skip(f"Database not built at {DB_PATH}; run the ingestion+dbt pipeline first.")
    try:
        from api.routes.insights import _build_sanitised_context
    except Exception as exc:  # pragma: no cover - import guard
        pytest.skip(f"insights module not importable: {exc}")
    con = sqlite3.connect(DB_PATH)
    try:
        return _build_sanitised_context(con)
    finally:
        con.close()


def _revenue_totals() -> list:
    con = sqlite3.connect(DB_PATH)
    try:
        rows = con.execute(
            "SELECT ROUND(SUM(monthly_revenue)) FROM mart_forecast_inputs "
            "GROUP BY category, year"
        ).fetchall()
        grand = con.execute(
            "SELECT ROUND(SUM(monthly_revenue)) FROM mart_forecast_inputs"
        ).fetchone()[0]
    finally:
        con.close()
    totals = [int(r[0]) for r in rows if r[0]]
    if grand:
        totals.append(int(grand))
    return totals


def test_context_is_a_relative_summary(context):
    """It should produce relative stats — percentages, shares, rankings."""
    assert context.strip(), "sanitised context is empty"
    assert "%" in context
    low = context.lower()
    assert any(k in low for k in ("share", "yoy", "growth", "rank")), (
        "context does not look like a relative-trend summary"
    )


def test_no_large_magnitude_numbers_leak(context):
    """
    Raw revenue totals are 6+ digit numbers. Nothing legitimate in the sanitised
    context (percentages, ranks, 4-digit years, small event counts) reaches six
    digits, so any 6+ digit run is a likely raw-financial leak.
    """
    big = re.findall(r"\d{6,}", context)
    assert not big, f"Possible raw-magnitude leak — found large numbers: {big[:5]}"


def test_specific_revenue_totals_absent(context):
    """No actual category/year or grand-total revenue figure appears verbatim."""
    leaked = [t for t in _revenue_totals() if str(t) in context]
    assert not leaked, f"Raw revenue totals leaked into LLM context: {leaked[:5]}"
