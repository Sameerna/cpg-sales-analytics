import os
import sqlite3
from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/data", tags=["data"])

DB_PATH = os.getenv("DB_PATH", "./data/cpg.db")


def _conn() -> sqlite3.Connection:
    try:
        return sqlite3.connect(DB_PATH)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"DB unavailable: {exc}")


class MonthlySummary(BaseModel):
    year: int
    month: int
    total_revenue: float
    total_transactions: int
    avg_unit_price: float


class CategorySummary(BaseModel):
    category: str
    year: int
    total_revenue: float
    avg_marketing_spend: float
    avg_discount_pct: float


class SummaryResponse(BaseModel):
    monthly: List[MonthlySummary]
    by_category: List[CategorySummary]


@router.get("/summary", response_model=SummaryResponse)
def data_summary() -> SummaryResponse:
    con = _conn()
    try:
        cur = con.cursor()

        cur.execute(
            """
            SELECT year, month,
                   SUM(monthly_revenue)      AS rev,
                   SUM(monthly_transactions) AS tx,
                   AVG(avg_unit_price)       AS price
            FROM mart_forecast_inputs
            GROUP BY year, month
            ORDER BY year, month
            """
        )
        monthly = [
            MonthlySummary(
                year=r[0],
                month=r[1],
                total_revenue=round(r[2], 2),
                total_transactions=int(r[3]),
                avg_unit_price=round(r[4], 2),
            )
            for r in cur.fetchall()
        ]

        cur.execute(
            """
            SELECT category, year,
                   SUM(monthly_revenue)        AS rev,
                   AVG(marketing_spend_usd)    AS mktg,
                   AVG(avg_discount_pct)       AS disc
            FROM mart_forecast_inputs
            GROUP BY category, year
            ORDER BY category, year
            """
        )
        by_category = [
            CategorySummary(
                category=r[0],
                year=r[1],
                total_revenue=round(r[2], 2),
                avg_marketing_spend=round(r[3], 2),
                avg_discount_pct=round(r[4], 2),
            )
            for r in cur.fetchall()
        ]

        return SummaryResponse(monthly=monthly, by_category=by_category)
    finally:
        con.close()
