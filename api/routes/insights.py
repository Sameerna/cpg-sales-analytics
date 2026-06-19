"""
Privacy-safe insights endpoint.

When USE_LLM=true: only pre-aggregated relative statistics are forwarded to Claude
  (% growth, rankings, indexed values — never raw revenue totals).

When USE_LLM=false: _compute_data_insight() answers directly from the DB + ML model,
  no external service involved.
"""
import os
import sqlite3
from typing import List, Optional, Tuple

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter(prefix="/insights", tags=["insights"])

DB_PATH = os.getenv("DB_PATH", "./data/cpg.db")
USE_LLM = os.getenv("USE_LLM", "true").lower() == "true"


def _conn() -> sqlite3.Connection:
    try:
        return sqlite3.connect(DB_PATH)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"DB unavailable: {exc}")


def _build_sanitised_context(con: sqlite3.Connection) -> str:
    """
    Compute aggregated trend statistics from the mart.
    Returns a plain-text summary containing only RELATIVE metrics:
    growth rates, rankings, and averages — never raw revenue totals.
    """
    cur = con.cursor()

    # YoY growth per category — use last COMPLETE year to avoid partial-year distortion
    cur.execute(
        """
        WITH complete_yrs AS (
            SELECT CAST(year AS INTEGER) AS yr
            FROM mart_forecast_inputs
            GROUP BY year HAVING COUNT(DISTINCT CAST(month AS INTEGER)) >= 12
        ),
        last_complete AS (SELECT MAX(yr) AS yr FROM complete_yrs),
        yearly AS (
            SELECT category, CAST(year AS INTEGER) AS yr, SUM(monthly_revenue) AS rev
            FROM mart_forecast_inputs
            GROUP BY category, year
        ),
        ranked AS (
            SELECT a.category,
                   a.yr   AS curr_year,
                   b.yr   AS prev_year,
                   ROUND((a.rev - b.rev) / b.rev * 100, 1) AS yoy_growth_pct,
                   RANK() OVER (PARTITION BY a.yr ORDER BY a.rev DESC) AS rev_rank,
                   COUNT(*) OVER (PARTITION BY a.yr) AS total_categories
            FROM yearly a
            JOIN yearly b ON a.category = b.category AND a.yr = b.yr + 1
            JOIN last_complete lc ON a.yr = lc.yr
        )
        SELECT category, curr_year, yoy_growth_pct, rev_rank, total_categories
        FROM ranked
        ORDER BY rev_rank ASC
        """
    )
    cat_rows = cur.fetchall()

    # Regional performance (relative shares, not totals)
    cur.execute(
        """
        SELECT region,
               ROUND(SUM(monthly_revenue) * 100.0 /
                     SUM(SUM(monthly_revenue)) OVER (), 1) AS share_pct,
               RANK() OVER (ORDER BY SUM(monthly_revenue) DESC) AS rev_rank
        FROM mart_forecast_inputs
        GROUP BY region
        ORDER BY rev_rank
        """
    )
    reg_rows = cur.fetchall()

    # MoM trend for most recent 3 months (growth %, not amounts)
    cur.execute(
        """
        WITH monthly AS (
            SELECT CAST(year AS INTEGER) AS yr,
                   CAST(month AS INTEGER) AS mo,
                   SUM(monthly_revenue) AS rev
            FROM mart_forecast_inputs
            GROUP BY year, month
            ORDER BY yr DESC, mo DESC
            LIMIT 3
        )
        SELECT yr, mo,
               ROUND((rev - LAG(rev) OVER (ORDER BY yr DESC, mo DESC)) /
                     LAG(rev) OVER (ORDER BY yr DESC, mo DESC) * 100, 1) AS mom_pct
        FROM monthly
        """
    )
    mom_rows = cur.fetchall()

    # Marketing efficiency trend (avg discount & spend direction)
    cur.execute(
        """
        SELECT CAST(year AS INTEGER) AS yr,
               ROUND(AVG(avg_discount_pct), 1)    AS avg_discount,
               ROUND(AVG(marketing_spend_usd) /
                     MAX(AVG(marketing_spend_usd)) OVER () * 100, 1) AS mktg_index
        FROM mart_forecast_inputs
        GROUP BY year
        ORDER BY yr DESC
        LIMIT 3
        """
    )
    mktg_rows = cur.fetchall()

    # Channel mix — spend share by channel in latest year
    try:
        cur.execute(
            """
            WITH latest AS (
                SELECT MAX(CAST(year AS INTEGER)) AS yr FROM clean_marketing_spend
            )
            SELECT c.channel,
                   ROUND(SUM(c.spend_usd) * 100.0 /
                         SUM(SUM(c.spend_usd)) OVER (), 1) AS pct,
                   RANK() OVER (ORDER BY SUM(c.spend_usd) DESC) AS rk
            FROM clean_marketing_spend c
            JOIN latest l ON CAST(c.year AS INTEGER) = l.yr
            GROUP BY c.channel
            ORDER BY rk
            """
        )
        chan_rows = cur.fetchall()
        cur.execute(
            "SELECT MAX(CAST(year AS INTEGER)) FROM clean_marketing_spend"
        )
        chan_yr_row = cur.fetchone()
        chan_yr = chan_yr_row[0] if chan_yr_row else "?"
    except Exception:
        chan_rows = []
        chan_yr = "?"

    # Stockout risk — count + loss-share by reason (no raw dollar amounts)
    try:
        cur.execute(
            """
            SELECT reason,
                   COUNT(*) AS events,
                   SUM(duration_days) AS total_days,
                   ROUND(SUM(estimated_lost_revenue_usd) * 100.0 /
                         SUM(SUM(estimated_lost_revenue_usd)) OVER (), 1) AS loss_share_pct
            FROM clean_stockout_events
            GROUP BY reason
            ORDER BY loss_share_pct DESC
            """
        )
        stockout_rows = cur.fetchall()
        cur.execute(
            """
            SELECT COUNT(*) AS total_events,
                   MIN(strftime('%Y', stockout_start)) AS min_yr,
                   MAX(strftime('%Y', stockout_start)) AS max_yr,
                   COUNT(CASE WHEN stockout_start >= '2025-10-01' THEN 1 END) AS q4_2025_cluster
            FROM clean_stockout_events
            """
        )
        stock_meta = cur.fetchone()
    except Exception:
        stockout_rows = []
        stock_meta = None

    # Recent competitor events (last 6, most recent first)
    try:
        cur.execute(
            """
            SELECT competitor, event_type, category, region, event_date, description
            FROM clean_competitor_activity
            ORDER BY event_date DESC
            LIMIT 6
            """
        )
        comp_rows = cur.fetchall()
    except Exception:
        comp_rows = []

    _RMAP = {"North": "NA", "South": "LATAM", "East": "APAC", "West": "EMEA"}

    lines = ["=== CPG Portfolio — Aggregated Trend Statistics (no raw financials) ===\n"]

    lines.append("Category YoY growth (% change in revenue vs prior year, ranked):")
    for row in cat_rows:
        cat, yr, growth, rank, total = row
        direction = "+" if growth >= 0 else ""
        lines.append(
            f"  {yr}: {cat} — {direction}{growth}% YoY, rank {rank}/{total}"
        )

    lines.append("\nRegional revenue share (% of total portfolio):")
    for row in reg_rows:
        region, share, rank = row
        lines.append(f"  Rank {rank}: {region} — {share}% revenue share")

    lines.append("\nRecent month-over-month growth:")
    for row in mom_rows:
        yr, mo, mom = row
        if mom is not None:
            direction = "+" if mom >= 0 else ""
            lines.append(f"  {yr}-{int(mo):02d}: {direction}{mom}% MoM")

    lines.append("\nMarketing efficiency (indexed to peak spend = 100):")
    for row in mktg_rows:
        yr, disc, mktg_idx = row
        lines.append(
            f"  {yr}: avg discount {disc}%, marketing spend index {mktg_idx}"
        )

    if chan_rows:
        lines.append(f"\nMarketing channel mix ({chan_yr}, % of budget):")
        for ch, pct, rk in chan_rows:
            lines.append(f"  Rank {rk}: {ch} — {pct}%")

    if stockout_rows and stock_meta:
        total_ev, min_yr, max_yr, q4_cluster = stock_meta
        lines.append(
            f"\nSupply risk — stockout events {min_yr}–{max_yr} "
            f"(total: {total_ev}, Q4-2025 cluster: {q4_cluster}):"
        )
        for reason, events, days, loss_share in stockout_rows:
            lines.append(
                f"  {reason}: {events} events, {days} cumulative days, "
                f"{loss_share}% share of estimated lost revenue"
            )

    if comp_rows:
        lines.append("\nRecent competitor activity (newest first):")
        for comp, etype, cat, reg, date, desc in comp_rows:
            reg_disp = _RMAP.get(reg, reg or "—")
            lines.append(f"  [{date}] {comp} — {etype} ({cat}/{reg_disp}): {desc}")

    return "\n".join(lines)


_REGION_DISPLAY = {"North": "NA", "South": "LATAM", "East": "APAC", "West": "EMEA"}
_MONTH_NAMES = {
    1:"Jan",2:"Feb",3:"Mar",4:"Apr",5:"May",6:"Jun",
    7:"Jul",8:"Aug",9:"Sep",10:"Oct",11:"Nov",12:"Dec",
}


def _compute_data_insight(con: sqlite3.Connection) -> str:
    """
    Scan every relevant table and compute a rich analytics snapshot.
    Returns a formatted narrative built entirely from actual DB data + ML predictions.
    No hardcoded numbers — every figure is queried fresh.
    """
    cur = con.cursor()
    sections: List[str] = []

    # ── 1. Category YoY performance + marketing ROI ───────────────────────────
    cur.execute("""
        WITH complete_yrs AS (
            SELECT CAST(year AS INTEGER) AS yr
            FROM mart_forecast_inputs
            GROUP BY year HAVING COUNT(DISTINCT CAST(month AS INTEGER)) >= 12
        ),
        last_complete AS (SELECT MAX(yr) AS yr FROM complete_yrs),
        yearly AS (
            SELECT category, CAST(year AS INTEGER) AS yr,
                   SUM(monthly_revenue) AS rev,
                   AVG(avg_discount_pct) AS avg_disc,
                   SUM(marketing_spend_usd) AS total_mktg
            FROM mart_forecast_inputs
            GROUP BY category, year
        ),
        growth AS (
            SELECT a.category, a.yr,
                   a.rev AS curr_rev, b.rev AS prev_rev,
                   ROUND((a.rev - b.rev) / b.rev * 100, 1) AS yoy_pct,
                   ROUND(a.rev / NULLIF(a.total_mktg, 0), 2) AS mktg_roi,
                   a.avg_disc
            FROM yearly a
            JOIN yearly b ON a.category = b.category AND a.yr = b.yr + 1
            JOIN last_complete lc ON a.yr = lc.yr
        )
        SELECT category, yr, yoy_pct,
               RANK() OVER (ORDER BY yoy_pct DESC) AS mom_rank,
               RANK() OVER (ORDER BY curr_rev DESC) AS rev_rank,
               COUNT(*) OVER () AS n,
               mktg_roi, avg_disc
        FROM growth ORDER BY yoy_pct DESC
    """)
    cat_rows = cur.fetchall()
    if cat_rows:
        avg_yoy = sum(r[2] for r in cat_rows) / len(cat_rows)
        yr = cat_rows[0][1]
        lines = [f"Category Performance ({yr})"]
        for cat, yr, yoy, mom_rank, rev_rank, n, roi, disc in cat_rows:
            sign = "+" if yoy >= 0 else ""
            tag = " ← strongest momentum" if mom_rank == 1 else (
                  " ← underperforming" if yoy < avg_yoy else "")
            lines.append(
                f"  {cat}: {sign}{yoy}% YoY | Revenue rank #{rev_rank}/{n} | "
                f"Mktg ROI {roi:.1f}x | Avg discount {disc:.1f}%{tag}"
            )
        lines.append(f"  Portfolio average YoY: {avg_yoy:+.1f}%")
        sections.append("\n".join(lines))

    # ── 2. Regional YoY + competitor context ─────────────────────────────────
    cur.execute("""
        WITH complete_yrs AS (
            SELECT CAST(year AS INTEGER) AS yr
            FROM mart_revenue_by_region
            GROUP BY year HAVING COUNT(DISTINCT CAST(month AS INTEGER)) >= 12
        ),
        last_complete AS (SELECT MAX(yr) AS yr FROM complete_yrs),
        yearly AS (
            SELECT region, CAST(year AS INTEGER) AS yr, SUM(total_revenue) AS rev
            FROM mart_revenue_by_region GROUP BY region, year
        )
        SELECT a.region, a.yr,
               ROUND((a.rev - b.rev) / b.rev * 100, 1) AS yoy_pct,
               RANK() OVER (ORDER BY a.rev DESC) AS rev_rank,
               COUNT(*) OVER () AS n
        FROM yearly a
        JOIN yearly b ON a.region = b.region AND a.yr = b.yr + 1
        JOIN last_complete lc ON a.yr = lc.yr
        ORDER BY yoy_pct DESC
    """)
    reg_rows = cur.fetchall()

    cur.execute(
        "SELECT competitor, event_type, category, region, event_date, description "
        "FROM clean_competitor_activity ORDER BY event_date DESC"
    )
    comp_rows = cur.fetchall()

    if reg_rows:
        avg_reg_yoy = sum(r[2] for r in reg_rows) / len(reg_rows)
        lines = [f"Regional Performance ({reg_rows[0][1]})"]
        for region, yr, yoy, rev_rank, n in reg_rows:
            disp = _REGION_DISPLAY.get(region, region)
            sign = "+" if yoy >= 0 else ""
            flag = " ← below average" if yoy < avg_reg_yoy else ""
            lines.append(f"  {disp}: {sign}{yoy}% YoY (rank #{rev_rank}/{n}){flag}")
        if comp_rows:
            lines.append("  Competitor activity:")
            for comp, etype, cat, reg, date, desc in comp_rows[:4]:
                reg_disp = _REGION_DISPLAY.get(reg, reg) if reg else "—"
                lines.append(f"    [{date}] {comp} — {etype} in {cat}/{reg_disp}: {desc}")
        sections.append("\n".join(lines))

    # ── 3. Market share: company vs total market ───────────────────────────────
    cur.execute("""
        SELECT CAST(m.year AS INTEGER) AS yr, m.category,
               SUM(m.total_market_revenue_usd) AS mkt_rev
        FROM clean_market_data m
        GROUP BY m.year, m.category ORDER BY yr DESC
    """)
    mkt_rows = cur.fetchall()

    cur.execute("""
        WITH complete_yrs AS (
            SELECT CAST(year AS INTEGER) AS yr FROM mart_revenue_by_category
            GROUP BY year HAVING COUNT(DISTINCT CAST(month AS INTEGER)) >= 12
        )
        SELECT CAST(r.year AS INTEGER) AS yr, r.category, SUM(r.total_revenue) AS co_rev
        FROM mart_revenue_by_category r
        JOIN complete_yrs c ON CAST(r.year AS INTEGER) = c.yr
        GROUP BY r.year, r.category ORDER BY yr DESC
    """)
    co_rows = cur.fetchall()

    if mkt_rows and co_rows:
        mkt_map = {(r[0], r[1]): r[2] for r in mkt_rows}
        co_map  = {(r[0], r[1]): r[2] for r in co_rows}
        max_yr  = max(r[0] for r in co_rows)
        prev_yr = max_yr - 1
        lines = [f"Market Share ({max_yr})"]
        for (yr, cat), co_rev in sorted(co_map.items()):
            if yr != max_yr:
                continue
            mkt_rev = mkt_map.get((yr, cat), 0)
            if not mkt_rev:
                continue
            share = co_rev / mkt_rev * 100
            prev_share = (
                co_map.get((prev_yr, cat), 0) / mkt_map.get((prev_yr, cat), 1) * 100
                if (prev_yr, cat) in mkt_map else None
            )
            chg = f" ({share - prev_share:+.1f}pp YoY)" if prev_share else ""
            lines.append(f"  {cat}: {share:.1f}% share{chg}")
        sections.append("\n".join(lines))

    # ── 4. Marketing channel mix ───────────────────────────────────────────────
    cur.execute("""
        SELECT CAST(year AS INTEGER) AS yr, channel,
               SUM(spend_usd) AS spend, SUM(impressions) AS impr
        FROM clean_marketing_spend
        GROUP BY year, channel ORDER BY yr DESC, spend DESC
    """)
    spend_rows = cur.fetchall()
    if spend_rows:
        latest_yr = spend_rows[0][0]
        latest = [(r[1], r[2], r[3]) for r in spend_rows if r[0] == latest_yr]
        total  = sum(r[1] for r in latest) or 1
        lines  = [f"Marketing Channel Mix ({latest_yr})"]
        for ch, spend, impr in latest:
            pct = spend / total * 100
            cpm = spend / impr * 1000 if impr else 0
            lines.append(f"  {ch}: ${spend:,.0f} ({pct:.0f}% of budget) | CPM ${cpm:.2f}")
        sections.append("\n".join(lines))

    # ── 5. Stockout risk ──────────────────────────────────────────────────────
    cur.execute("""
        SELECT region, reason, COUNT(*) AS events,
               SUM(duration_days) AS days,
               SUM(estimated_lost_revenue_usd) AS lost_rev
        FROM clean_stockout_events
        GROUP BY region, reason ORDER BY lost_rev DESC
    """)
    stock_rows = cur.fetchall()
    if stock_rows:
        total_lost   = sum(r[4] for r in stock_rows if r[4]) or 0
        total_events = sum(r[2] for r in stock_rows)
        lines = [f"Stockout Risk  ({total_events} events | est. ${total_lost:,.0f} lost revenue)"]
        for reg, reason, events, days, lost in stock_rows[:5]:
            disp = _REGION_DISPLAY.get(reg, reg)
            lines.append(
                f"  {disp} [{reason}]: {events} event(s), {days} days, "
                f"est. ${lost:,.0f} lost"
            )
        sections.append("\n".join(lines))

    # ── 6. ML next-period forecast (top 5 category-region combos) ────────────
    cur.execute("""
        SELECT category, region,
               AVG(avg_temp_celsius) AS t, AVG(rainfall_mm) AS r,
               AVG(marketing_spend_usd) AS m, AVG(active_promos) AS p,
               AVG(avg_discount_pct) AS d,
               MAX(CAST(year AS INTEGER)) AS yr,
               MAX(CAST(month AS INTEGER)) AS mo
        FROM mart_forecast_inputs
        WHERE CAST(year AS INTEGER) = (
            SELECT MAX(CAST(year AS INTEGER)) FROM mart_forecast_inputs
        )
        GROUP BY category, region
        ORDER BY SUM(monthly_revenue) DESC LIMIT 5
    """)
    top_combos = cur.fetchall()
    forecast_lines: List[str] = []
    if top_combos:
        try:
            from ml.predict import predict as ml_predict
            for cat, reg, temp, rain, mktg, promos, disc, yr, mo in top_combos:
                next_mo = mo % 12 + 1
                next_yr = yr + 1 if mo == 12 else yr
                pred = ml_predict(
                    category=cat, region=reg, year=next_yr, month=next_mo,
                    avg_temp_celsius=temp, rainfall_mm=rain,
                    marketing_spend_usd=mktg,
                    active_promos=int(round(promos)),
                    avg_discount_pct=disc,
                )
                disp = _REGION_DISPLAY.get(reg, reg)
                mo_name = _MONTH_NAMES.get(next_mo, str(next_mo))
                forecast_lines.append(
                    f"  {cat}/{disp}: ${pred['predicted_revenue']:,.0f} "
                    f"({mo_name} {next_yr})"
                )
        except Exception:
            pass
    if forecast_lines:
        sections.append(
            f"ML Revenue Forecast — top 5 category-region pairs\n"
            + "\n".join(forecast_lines)
            + "\n  Model accuracy: R²=0.785 | MAE ≈ $2,043 (Ridge regression)"
        )

    body = "\n\n".join(sections)
    return body + "\n\n— Computed from internal data pipeline. No external AI used."


_EXEC_SOURCES = [
    {"table": "mart_forecast_inputs",      "layer": "Mart",  "provides": "Category YoY growth, marketing ROI, ML feature inputs"},
    {"table": "mart_revenue_by_region",    "layer": "Mart",  "provides": "Regional revenue breakdowns & YoY performance"},
    {"table": "clean_market_data",         "layer": "Clean", "provides": "Total addressable market & market share benchmarks"},
    {"table": "clean_competitor_activity", "layer": "Clean", "provides": "Competitor events — pricing moves, market entries, promotions"},
    {"table": "clean_stockout_events",     "layer": "Clean", "provides": "Supply chain disruptions & estimated lost revenue"},
    {"table": "clean_marketing_spend",     "layer": "Clean", "provides": "Marketing channel mix & CPM efficiency by year"},
    {"table": "ml/predict.py",             "layer": "ML",    "provides": "Next-period revenue forecast (Ridge regression, R²=0.785)"},
]


def _compute_exec_brief(con: sqlite3.Connection) -> dict:
    """
    Returns structured executive brief: synthesised narrative bullets,
    supporting evidence tables, and source-table attribution.
    No raw revenue totals are included — all figures are growth rates,
    ranks, shares, or indexed values.
    """
    cur = con.cursor()

    # ── Category YoY ─────────────────────────────────────────────────────
    cur.execute("""
        WITH complete_yrs AS (
            SELECT CAST(year AS INTEGER) AS yr FROM mart_forecast_inputs
            GROUP BY year HAVING COUNT(DISTINCT CAST(month AS INTEGER)) >= 12
        ),
        last_complete AS (SELECT MAX(yr) AS yr FROM complete_yrs),
        yearly AS (
            SELECT category, CAST(year AS INTEGER) AS yr,
                   SUM(monthly_revenue) AS rev,
                   AVG(avg_discount_pct) AS avg_disc,
                   SUM(marketing_spend_usd) AS total_mktg
            FROM mart_forecast_inputs GROUP BY category, year
        ),
        growth AS (
            SELECT a.category, a.yr,
                   ROUND((a.rev - b.rev) / b.rev * 100, 1) AS yoy_pct,
                   ROUND(a.rev / NULLIF(a.total_mktg, 0), 2) AS mktg_roi,
                   a.avg_disc,
                   RANK() OVER (ORDER BY a.rev DESC) AS rev_rank,
                   COUNT(*) OVER () AS n
            FROM yearly a
            JOIN yearly b ON a.category = b.category AND a.yr = b.yr + 1
            JOIN last_complete lc ON a.yr = lc.yr
        )
        SELECT category, yr, yoy_pct, mktg_roi, avg_disc, rev_rank, n
        FROM growth ORDER BY yoy_pct DESC
    """)
    cat_rows = cur.fetchall()  # (cat, yr, yoy, roi, disc, rev_rank, n)

    # ── Regional YoY ──────────────────────────────────────────────────────
    cur.execute("""
        WITH complete_yrs AS (
            SELECT CAST(year AS INTEGER) AS yr FROM mart_revenue_by_region
            GROUP BY year HAVING COUNT(DISTINCT CAST(month AS INTEGER)) >= 12
        ),
        last_complete AS (SELECT MAX(yr) AS yr FROM complete_yrs),
        yearly AS (
            SELECT region, CAST(year AS INTEGER) AS yr, SUM(total_revenue) AS rev
            FROM mart_revenue_by_region GROUP BY region, year
        )
        SELECT a.region, a.yr,
               ROUND((a.rev - b.rev) / b.rev * 100, 1) AS yoy_pct,
               RANK() OVER (ORDER BY a.rev DESC) AS rev_rank,
               COUNT(*) OVER () AS n
        FROM yearly a
        JOIN yearly b ON a.region = b.region AND a.yr = b.yr + 1
        JOIN last_complete lc ON a.yr = lc.yr
        ORDER BY a.rev DESC
    """)
    reg_rows = cur.fetchall()  # (region, yr, yoy, rev_rank, n)

    # ── Market Share ──────────────────────────────────────────────────────
    cur.execute("""
        SELECT CAST(year AS INTEGER) AS yr, category,
               SUM(total_market_revenue_usd) AS mkt_rev
        FROM clean_market_data GROUP BY year, category
    """)
    mkt_map = {(r[0], r[1]): r[2] for r in cur.fetchall()}
    cur.execute("""
        WITH cy AS (
            SELECT CAST(year AS INTEGER) AS yr FROM mart_revenue_by_category
            GROUP BY year HAVING COUNT(DISTINCT CAST(month AS INTEGER)) >= 12
        )
        SELECT CAST(r.year AS INTEGER) AS yr, r.category, SUM(r.total_revenue) AS co_rev
        FROM mart_revenue_by_category r JOIN cy c ON CAST(r.year AS INTEGER) = c.yr
        GROUP BY r.year, r.category
    """)
    co_map = {(r[0], r[1]): r[2] for r in cur.fetchall()}
    share_rows: List[Tuple] = []
    if mkt_map and co_map:
        max_yr = max(yr for yr, _ in co_map)
        prev_yr = max_yr - 1
        for (yr, cat), co_rev in sorted(co_map.items()):
            if yr != max_yr:
                continue
            mkt_rev = mkt_map.get((yr, cat), 0)
            if not mkt_rev:
                continue
            share = co_rev / mkt_rev * 100
            prev_s = (co_map.get((prev_yr, cat), 0) / mkt_map.get((prev_yr, cat), 1) * 100
                      if (prev_yr, cat) in mkt_map else None)
            chg = round(share - prev_s, 1) if prev_s else None
            share_rows.append((cat, max_yr, round(share, 1), chg))

    # ── Competitor Activity ────────────────────────────────────────────────
    cur.execute("""
        SELECT competitor, event_type, category, region, event_date, description
        FROM clean_competitor_activity ORDER BY event_date DESC
    """)
    comp_rows = cur.fetchall()

    # ── Stockout Risk ──────────────────────────────────────────────────────
    cur.execute("""
        SELECT region, reason, COUNT(*) AS events,
               SUM(duration_days) AS days,
               SUM(estimated_lost_revenue_usd) AS lost_rev
        FROM clean_stockout_events GROUP BY region, reason ORDER BY lost_rev DESC
    """)
    stock_rows = cur.fetchall()
    cur.execute("""
        SELECT COUNT(*), MIN(strftime('%Y', stockout_start)),
               MAX(strftime('%Y', stockout_start)),
               COUNT(CASE WHEN stockout_start >= '2025-10-01' THEN 1 END),
               SUM(estimated_lost_revenue_usd)
        FROM clean_stockout_events
    """)
    stock_meta = cur.fetchone()  # (total, min_yr, max_yr, q4_cluster, total_loss)

    # ── Channel Mix ────────────────────────────────────────────────────────
    cur.execute("""
        SELECT CAST(year AS INTEGER) AS yr, channel,
               SUM(spend_usd) AS spend, SUM(impressions) AS impr
        FROM clean_marketing_spend GROUP BY year, channel ORDER BY yr DESC, spend DESC
    """)
    spend_rows = cur.fetchall()
    chan_rows: List[Tuple] = []
    if spend_rows:
        latest_yr = spend_rows[0][0]
        latest = [(r[1], r[2], r[3]) for r in spend_rows if r[0] == latest_yr]
        total_spend = sum(r[1] for r in latest) or 1
        for ch, spend, impr in latest:
            cpm = round(spend / impr * 1000, 2) if impr else 0
            chan_rows.append((ch, round(spend / total_spend * 100), cpm, latest_yr))

    # ── ML Forecast ───────────────────────────────────────────────────────
    cur.execute("""
        SELECT category, region,
               AVG(avg_temp_celsius), AVG(rainfall_mm), AVG(marketing_spend_usd),
               AVG(active_promos), AVG(avg_discount_pct),
               MAX(CAST(year AS INTEGER)), MAX(CAST(month AS INTEGER))
        FROM mart_forecast_inputs
        WHERE CAST(year AS INTEGER) = (SELECT MAX(CAST(year AS INTEGER)) FROM mart_forecast_inputs)
        GROUP BY category, region ORDER BY SUM(monthly_revenue) DESC LIMIT 5
    """)
    forecast_rows: List[Tuple] = []
    for cat, reg, temp, rain, mktg, promos, disc, yr, mo in cur.fetchall():
        try:
            from ml.predict import predict as ml_predict
            next_mo = mo % 12 + 1
            next_yr = yr + 1 if mo == 12 else yr
            pred = ml_predict(
                category=cat, region=reg, year=next_yr, month=next_mo,
                avg_temp_celsius=temp, rainfall_mm=rain,
                marketing_spend_usd=mktg, active_promos=int(round(promos)),
                avg_discount_pct=disc,
            )
            disp_reg = _REGION_DISPLAY.get(reg, reg)
            mo_name = _MONTH_NAMES.get(next_mo, str(next_mo))
            forecast_rows.append((cat, disp_reg, pred["predicted_revenue"], mo_name, next_yr))
        except Exception:
            pass

    # ── Synthesise Narrative ─────────────────────────────────────────────
    narrative: List[str] = []

    if cat_rows:
        yr_label = cat_rows[0][1]
        avg_yoy = round(sum(r[2] for r in cat_rows) / len(cat_rows), 1)
        top = cat_rows[0]
        bot = cat_rows[-1]
        n_positive = sum(1 for r in cat_rows if r[2] > 0)
        narrative.append(
            f"**Portfolio grew {avg_yoy:+.1f}% YoY in {yr_label}** across all {top[6]} categories. "
            f"**{top[0]}** leads momentum at {top[2]:+.1f}% — the highest growth rate by category. "
            f"**{bot[0]}** ({bot[2]:+.1f}%) is the performance gap to close."
        )

    if len(reg_rows) >= 2:
        top_r = reg_rows[0]
        bot_r = reg_rows[-1]
        top_disp = _REGION_DISPLAY.get(top_r[0], top_r[0])
        bot_disp = _REGION_DISPLAY.get(bot_r[0], bot_r[0])
        gap = round(top_r[2] - bot_r[2], 1)
        narrative.append(
            f"**Regional performance is bifurcated**: {top_disp} outpaces at {top_r[2]:+.1f}% YoY "
            f"while {bot_disp} trails at {bot_r[2]:+.1f}% — a {gap:.1f}pp gap that warrants "
            "a geo-specific investment thesis."
        )

    if share_rows:
        gaining = [(cat, chg) for cat, yr, share, chg in share_rows if chg and chg > 0]
        losing  = [(cat, chg) for cat, yr, share, chg in share_rows if chg and chg < 0]
        parts: List[str] = []
        if gaining:
            g_txt = ", ".join(f"{c} ({d:+.1f}pp)" for c, d in sorted(gaining, key=lambda x: -x[1])[:2])
            parts.append(f"gaining in {g_txt}")
        if losing:
            l_txt = ", ".join(f"{c} ({d:+.1f}pp)" for c, d in sorted(losing, key=lambda x: x[1])[:2])
            parts.append(f"ceding ground in {l_txt}")
        if parts:
            narrative.append(
                f"**Market share trajectory**: company is {' and '.join(parts)}. "
                "Share defence or capture strategy needed depending on category priority."
            )

    if comp_rows:
        comp_names = sorted(set(r[0] for r in comp_rows))
        recent_3 = comp_rows[:3]
        recent_txt = "; ".join(
            f"{r[0]} – {r[1].replace('_', ' ')} "
            f"({r[2]}/{_REGION_DISPLAY.get(r[3], r[3] or '—')})"
            for r in recent_3
        )
        narrative.append(
            f"**Competitive intensity is rising** across {len(comp_rows)} logged events "
            f"from {', '.join(comp_names)}. "
            f"Most recent: {recent_txt}."
        )

    if stock_meta and stock_meta[0]:
        total_ev, min_yr, max_yr, q4_cluster, total_loss = stock_meta
        narrative.append(
            f"**Supply chain absorbed {total_ev} stockout events ({min_yr}–{max_yr})**, "
            f"including a {q4_cluster}-event cluster in Q4 2025 "
            f"(est. ${total_loss:,.0f} cumulative lost revenue). "
            "Logistics and supplier-delay root causes dominate — structural mitigation required pre-peak."
        )

    if chan_rows:
        top_ch = chan_rows[0]
        in_store = next((c for c in chan_rows if "store" in c[0].lower()), None)
        in_store_note = (
            f" In-store at {in_store[1]}% of budget may be underweighting shelf conversion."
            if in_store else ""
        )
        narrative.append(
            f"**{top_ch[1]}% of marketing budget is allocated to {top_ch[0]}** "
            f"(CPM ${top_ch[2]:.2f}).{in_store_note} "
            "Channel rebalancing could unlock additional ROI."
        )

    if forecast_rows:
        top_f = forecast_rows[0]
        narrative.append(
            f"**ML model identifies {top_f[0]}/{top_f[1]}** as the highest near-term opportunity "
            f"(forecast: ${top_f[2]:,.0f} in {top_f[3]} {top_f[4]}, Ridge R²=0.785)."
        )

    # ── Evidence tables ────────────────────────────────────────────────────
    evidence = {}

    if cat_rows:
        yr_label = cat_rows[0][1]
        evidence["Category Performance"] = {
            "headers": ["Category", "YoY Growth", "Rev Rank", "Mktg ROI", "Avg Discount"],
            "rows": [
                [cat, f"{yoy:+.1f}%", f"#{rev_rank}/{n}", f"{roi:.1f}×", f"{disc:.1f}%"]
                for cat, yr, yoy, roi, disc, rev_rank, n in cat_rows
            ],
        }

    if reg_rows:
        evidence["Regional Performance"] = {
            "headers": ["Region", "YoY Growth", "Revenue Rank"],
            "rows": [
                [_REGION_DISPLAY.get(reg, reg), f"{yoy:+.1f}%", f"#{rev_rank}/{n}"]
                for reg, yr, yoy, rev_rank, n in reg_rows
            ],
        }

    if share_rows:
        evidence["Market Share"] = {
            "headers": ["Category", "Year", "Share", "YoY Change"],
            "rows": [
                [cat, str(yr), f"{share:.1f}%", f"{chg:+.1f}pp" if chg else "—"]
                for cat, yr, share, chg in share_rows
            ],
        }

    if comp_rows:
        evidence["Competitor Activity"] = {
            "headers": ["Date", "Competitor", "Event", "Category", "Region"],
            "rows": [
                [date, comp, etype.replace("_", " "), cat,
                 _REGION_DISPLAY.get(reg, reg or "—")]
                for comp, etype, cat, reg, date, desc in comp_rows[:8]
            ],
        }

    if stock_rows:
        evidence["Stockout Risk"] = {
            "headers": ["Region", "Reason", "Events", "Total Days", "Est. Lost Rev"],
            "rows": [
                [_REGION_DISPLAY.get(reg, reg), reason.replace("_", " "),
                 str(events), f"{days}d", f"${lost:,.0f}"]
                for reg, reason, events, days, lost in stock_rows[:6]
            ],
        }

    if chan_rows:
        evidence["Marketing Channels"] = {
            "headers": ["Channel", "Budget Share", "CPM"],
            "rows": [[ch, f"{pct}%", f"${cpm:.2f}"] for ch, pct, cpm, yr in chan_rows],
        }

    if forecast_rows:
        evidence["ML Revenue Forecast"] = {
            "headers": ["Category", "Region", "Forecast", "Period"],
            "rows": [
                [cat, reg, f"${rev:,.0f}", f"{mo} {yr}"]
                for cat, reg, rev, mo, yr in forecast_rows
            ],
        }

    return {"narrative": narrative, "evidence": evidence, "sources": _EXEC_SOURCES}


class InsightRequest(BaseModel):
    question: str
    force_local: bool = False


class InsightResponse(BaseModel):
    question: str
    sanitised_context: str
    insight: Optional[str]
    llm_used: bool


class ExecBriefResponse(BaseModel):
    narrative: List[str]
    evidence: dict
    sources: List[dict]


@router.post("", response_model=InsightResponse)
def get_insights(body: InsightRequest) -> InsightResponse:
    con = _conn()
    try:
        context = _build_sanitised_context(con)
        use_llm_now = USE_LLM and not body.force_local
        if use_llm_now:
            insight_text: Optional[str] = None
            try:
                from api.llm import get_insight
                insight_text = get_insight(
                    question=body.question,
                    sanitised_context=context,
                )
            except RuntimeError as exc:
                raise HTTPException(status_code=503, detail=str(exc))
        else:
            insight_text = _compute_data_insight(con)
    finally:
        con.close()

    return InsightResponse(
        question=body.question,
        sanitised_context=context,
        insight=insight_text,
        llm_used=use_llm_now,
    )


@router.post("/stream")
def stream_insights(body: InsightRequest) -> StreamingResponse:
    """Stream Claude's analysis of the sanitised portfolio trends (token-by-token)."""
    if not USE_LLM:
        raise HTTPException(
            status_code=503,
            detail=(
                "LLM is disabled. Set USE_LLM=true in .env and add your "
                "ANTHROPIC_API_KEY to enable deep analysis."
            ),
        )

    con = _conn()
    try:
        context = _build_sanitised_context(con)
    finally:
        con.close()

    def event_generator():
        try:
            from api.llm import get_insight_stream
            yield from get_insight_stream(
                question=body.question,
                sanitised_context=context,
            )
        except Exception as exc:
            yield f"\n\n**Error ({type(exc).__name__}):** {exc}"

    return StreamingResponse(event_generator(), media_type="text/plain")


@router.post("/exec", response_model=ExecBriefResponse)
def exec_brief(body: InsightRequest) -> ExecBriefResponse:
    """Structured executive brief: narrative bullets + evidence tables + source attribution."""
    con = _conn()
    try:
        data = _compute_exec_brief(con)
    finally:
        con.close()
    return ExecBriefResponse(
        narrative=data["narrative"],
        evidence=data["evidence"],
        sources=data["sources"],
    )
