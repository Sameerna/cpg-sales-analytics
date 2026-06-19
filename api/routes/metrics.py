import os
import sqlite3
from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/metrics", tags=["metrics"])

DB_PATH = os.getenv("DB_PATH", "./data/cpg.db")


def _conn() -> sqlite3.Connection:
    try:
        return sqlite3.connect(DB_PATH)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"DB unavailable: {exc}")


class CategoryRevenue(BaseModel):
    category: str
    total_revenue: float
    revenue_share_pct: float


class RegionRevenue(BaseModel):
    region: str
    total_revenue: float
    revenue_share_pct: float


class MetricsResponse(BaseModel):
    total_revenue: float
    total_transactions: int
    top_category: str
    top_region: str
    mom_growth_pct: float
    categories: List[CategoryRevenue]
    regions: List[RegionRevenue]


@router.get("", response_model=MetricsResponse)
def get_metrics() -> MetricsResponse:
    con = _conn()
    try:
        cur = con.cursor()

        cur.execute(
            "SELECT SUM(monthly_revenue), SUM(monthly_transactions) FROM mart_forecast_inputs"
        )
        total_rev, total_tx = cur.fetchone()

        cur.execute(
            """
            SELECT category, SUM(monthly_revenue) AS rev
            FROM mart_forecast_inputs
            GROUP BY category
            ORDER BY rev DESC
            LIMIT 1
            """
        )
        top_cat = cur.fetchone()[0]

        cur.execute(
            """
            SELECT region, SUM(monthly_revenue) AS rev
            FROM mart_forecast_inputs
            GROUP BY region
            ORDER BY rev DESC
            LIMIT 1
            """
        )
        top_reg = cur.fetchone()[0]

        # MoM growth: compare most recent month vs the one before it
        cur.execute(
            """
            SELECT CAST(year AS INTEGER) AS yr,
                   CAST(month AS INTEGER) AS mo,
                   SUM(monthly_revenue) AS rev
            FROM mart_forecast_inputs
            GROUP BY year, month
            ORDER BY yr DESC, mo DESC
            LIMIT 2
            """
        )
        rows = cur.fetchall()
        if len(rows) == 2:
            mom_growth = round((rows[0][2] - rows[1][2]) / rows[1][2] * 100, 2)
        else:
            mom_growth = 0.0

        cur.execute(
            """
            SELECT category, SUM(monthly_revenue) AS rev
            FROM mart_forecast_inputs
            GROUP BY category
            ORDER BY rev DESC
            """
        )
        cat_rows = cur.fetchall()
        categories = [
            CategoryRevenue(
                category=r[0],
                total_revenue=round(r[1], 2),
                revenue_share_pct=round(r[1] / total_rev * 100, 2),
            )
            for r in cat_rows
        ]

        cur.execute(
            """
            SELECT region, SUM(monthly_revenue) AS rev
            FROM mart_forecast_inputs
            GROUP BY region
            ORDER BY rev DESC
            """
        )
        reg_rows = cur.fetchall()
        regions = [
            RegionRevenue(
                region=r[0],
                total_revenue=round(r[1], 2),
                revenue_share_pct=round(r[1] / total_rev * 100, 2),
            )
            for r in reg_rows
        ]

        return MetricsResponse(
            total_revenue=round(total_rev, 2),
            total_transactions=int(total_tx),
            top_category=top_cat,
            top_region=top_reg,
            mom_growth_pct=mom_growth,
            categories=categories,
            regions=regions,
        )
    finally:
        con.close()
