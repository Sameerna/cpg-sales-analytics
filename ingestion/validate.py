"""
Pre-dbt validation: cleans raw tables and writes bad rows to rejected_records.
Every bad row is quarantined with a reason_code — never silently dropped.

Run: python ingestion/validate.py
"""
import os
import re
import sqlite3
from datetime import datetime
from typing import Optional

from dateutil import parser as dateutil_parser

DB_PATH = os.getenv("DB_PATH", "./data/cpg.db")

REGION_ALIASES = {
    "n": "North", "north": "North", "north region": "North",
    "s": "South", "south": "South", "south region": "South",
    "e": "East",  "east":  "East",  "east region":  "East",
    "w": "West",  "west":  "West",  "west region":  "West",
}

VALID_CHANNELS = {"pos", "online"}


# ── helpers ──────────────────────────────────────────────────────────────────

def normalise_text(val: Optional[str]) -> str:
    return val.strip().lower() if val else ""


def parse_timestamp(raw: str) -> Optional[str]:
    raw = raw.strip()
    try:
        if raw.isdigit():
            return datetime.fromtimestamp(int(raw)).isoformat()
        return dateutil_parser.parse(raw).isoformat()
    except Exception:
        return None


def reject(cur: sqlite3.Cursor, source_table: str, row_id: str, reason_code: str, raw_row: dict) -> None:
    import json
    cur.execute(
        """
        INSERT INTO rejected_records (source_table, row_identifier, reason_code, raw_data)
        VALUES (?, ?, ?, ?)
        """,
        (source_table, row_id, reason_code, json.dumps(raw_row)),
    )


# ── table-level validators ────────────────────────────────────────────────────

def validate_transactions(con: sqlite3.Connection) -> dict:
    cur    = con.cursor()
    rows   = cur.execute("SELECT * FROM raw_transactions").fetchall()
    cols   = [d[0] for d in cur.description]

    # Load valid store ids for orphan check
    valid_stores = {r[0] for r in cur.execute("SELECT store_id FROM raw_stores").fetchall()}
    seen_txn_ids: set[str] = set()
    accepted = dupes = bad_ts = null_critical = orphan = out_of_range = 0

    clean_rows = []
    for raw in rows:
        row = dict(zip(cols, raw))
        tid = row.get("transaction_id", "")

        # Duplicate txn id — keep first
        if tid in seen_txn_ids:
            reject(cur, "transactions", tid, "DUPLICATE_TXN_ID", row)
            dupes += 1
            continue
        seen_txn_ids.add(tid)

        # Parse timestamp
        ts_parsed = parse_timestamp(row.get("timestamp", ""))
        if not ts_parsed:
            reject(cur, "transactions", tid, "UNPARSEABLE_TIMESTAMP", row)
            bad_ts += 1
            continue

        # Null critical fields
        if not row.get("quantity") or not row.get("unit_price"):
            reject(cur, "transactions", tid, "NULL_CRITICAL_FIELD", row)
            null_critical += 1
            continue

        # Out-of-range quantity
        try:
            qty = int(row["quantity"])
        except ValueError:
            reject(cur, "transactions", tid, "INVALID_QUANTITY", row)
            null_critical += 1
            continue

        if qty < 0:
            reject(cur, "transactions", tid, "NEGATIVE_QUANTITY", row)
            out_of_range += 1
            continue
        if qty == 0:
            reject(cur, "transactions", tid, "ZERO_QUANTITY", row)
            out_of_range += 1
            continue

        try:
            price = float(row["unit_price"])
            if price <= 0:
                raise ValueError
        except ValueError:
            reject(cur, "transactions", tid, "INVALID_PRICE", row)
            null_critical += 1
            continue

        # Orphaned store
        if row.get("store_id") not in valid_stores:
            reject(cur, "transactions", tid, "ORPHAN_STORE_ID", row)
            orphan += 1
            continue

        # Normalise channel
        ch = normalise_text(row.get("channel", ""))
        ch_norm = ch if ch in VALID_CHANNELS else "unknown"

        clean_rows.append((
            tid, ts_parsed,
            row.get("sku_id") or None,
            row.get("store_id"),
            qty, price, ch_norm,
            row.get("customer_id") or None,
        ))
        accepted += 1

    cur.execute("DROP TABLE IF EXISTS clean_transactions")
    cur.execute("""
        CREATE TABLE clean_transactions (
            transaction_id TEXT PRIMARY KEY,
            timestamp      TEXT,
            sku_id         TEXT,
            store_id       TEXT,
            quantity       INTEGER,
            unit_price     REAL,
            channel        TEXT,
            customer_id    TEXT
        )
    """)
    cur.executemany("INSERT INTO clean_transactions VALUES (?,?,?,?,?,?,?,?)", clean_rows)
    con.commit()
    return {"accepted": accepted, "dupes": dupes, "bad_ts": bad_ts,
            "null_critical": null_critical, "orphan": orphan, "out_of_range": out_of_range}


def validate_products(con: sqlite3.Connection) -> dict:
    cur  = con.cursor()
    rows = cur.execute("SELECT * FROM raw_products").fetchall()
    cols = [d[0] for d in cur.description]
    seen: set[str] = set()
    clean_rows = []; dupes = 0

    for raw in rows:
        row = dict(zip(cols, raw))
        sku = row.get("sku_id", "")
        if sku in seen:
            reject(cur, "products", sku, "DUPLICATE_SKU_ID", row)
            dupes += 1
            continue
        seen.add(sku)
        clean_rows.append((
            sku,
            row.get("category", "").strip().title() or "Unknown",
            row.get("subcategory", "").strip().title() or "Unknown",
            row.get("brand") or "Unknown",
            row.get("package_size") or "Unknown",
            float(row["list_price"]) if row.get("list_price") else None,
            row.get("launch_date") or None,
            row.get("is_new_launch", "N"),
        ))

    cur.execute("DROP TABLE IF EXISTS clean_products")
    cur.execute("""
        CREATE TABLE clean_products (
            sku_id TEXT PRIMARY KEY, category TEXT, subcategory TEXT,
            brand TEXT, package_size TEXT, list_price REAL,
            launch_date TEXT, is_new_launch TEXT
        )
    """)
    cur.executemany("INSERT INTO clean_products VALUES (?,?,?,?,?,?,?,?)", clean_rows)
    con.commit()
    return {"accepted": len(clean_rows), "dupes": dupes}


def validate_stores(con: sqlite3.Connection) -> dict:
    cur  = con.cursor()
    rows = cur.execute("SELECT * FROM raw_stores").fetchall()
    cols = [d[0] for d in cur.description]
    clean_rows = []

    for raw in rows:
        row    = dict(zip(cols, raw))
        region = REGION_ALIASES.get(normalise_text(row.get("region", "")), "Unknown")
        clean_rows.append((
            row["store_id"], region,
            row.get("store_type", "Unknown"),
            row.get("store_tier", "B"),
            int(row["store_size_sqm"]) if row.get("store_size_sqm") else None,
            int(row["weekly_footfall_estimate"]) if row.get("weekly_footfall_estimate") else None,
            row.get("has_online_delivery", "N"),
            row.get("demographic_segment") or "Unknown",
        ))

    cur.execute("DROP TABLE IF EXISTS clean_stores")
    cur.execute("""
        CREATE TABLE clean_stores (
            store_id TEXT PRIMARY KEY, region TEXT, store_type TEXT,
            store_tier TEXT, store_size_sqm INTEGER,
            weekly_footfall_estimate INTEGER, has_online_delivery TEXT,
            demographic_segment TEXT
        )
    """)
    cur.executemany("INSERT INTO clean_stores VALUES (?,?,?,?,?,?,?,?)", clean_rows)
    con.commit()
    return {"accepted": len(clean_rows)}


def validate_promotions(con: sqlite3.Connection) -> dict:
    cur  = con.cursor()
    rows = cur.execute("SELECT * FROM raw_promotions").fetchall()
    cols = [d[0] for d in cur.description]
    valid_skus = {r[0] for r in cur.execute("SELECT sku_id FROM raw_products").fetchall()}
    clean_rows = []; bad_dates = 0; unknown_sku = 0

    for raw in rows:
        row = dict(zip(cols, raw))
        pid = row.get("promo_id", "")

        try:
            start = datetime.fromisoformat(str(row["start_date"])).date()
            end   = datetime.fromisoformat(str(row["end_date"])).date()
        except Exception:
            reject(cur, "promotions", pid, "UNPARSEABLE_DATE", row)
            bad_dates += 1
            continue

        if end < start:
            reject(cur, "promotions", pid, "END_BEFORE_START", row)
            bad_dates += 1
            continue

        if row.get("sku_id") not in valid_skus:
            reject(cur, "promotions", pid, "UNKNOWN_SKU_ID", row)
            unknown_sku += 1
            continue

        clean_rows.append((
            pid, row["sku_id"],
            row.get("category", "Unknown"),
            str(start), str(end),
            float(row["discount_pct"]) if row.get("discount_pct") else 0.0,
            row.get("channel", "all"),
        ))

    cur.execute("DROP TABLE IF EXISTS clean_promotions")
    cur.execute("""
        CREATE TABLE clean_promotions (
            promo_id TEXT PRIMARY KEY, sku_id TEXT, category TEXT,
            start_date TEXT, end_date TEXT, discount_pct REAL, channel TEXT
        )
    """)
    cur.executemany("INSERT INTO clean_promotions VALUES (?,?,?,?,?,?,?)", clean_rows)
    con.commit()
    return {"accepted": len(clean_rows), "bad_dates": bad_dates, "unknown_sku": unknown_sku}


def validate_passthrough(con: sqlite3.Connection, src: str, dest: str, pk: str) -> dict:
    """For tables with no quality issues to quarantine — just copy to clean_*."""
    cur  = con.cursor()
    rows = cur.execute(f"SELECT * FROM {src}").fetchall()
    cols = [d[0] for d in cur.description]
    placeholders = ", ".join("?" for _ in cols)
    cols_ddl     = ", ".join(f'"{c}" TEXT' for c in cols)

    cur.execute(f"DROP TABLE IF EXISTS {dest}")
    cur.execute(f"CREATE TABLE {dest} ({cols_ddl})")
    cur.executemany(f"INSERT INTO {dest} VALUES ({placeholders})", rows)
    con.commit()
    return {"accepted": len(rows)}


# ── orchestrator ─────────────────────────────────────────────────────────────

def main() -> None:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    cur.execute("DROP TABLE IF EXISTS rejected_records")
    cur.execute("""
        CREATE TABLE rejected_records (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            source_table TEXT,
            row_identifier TEXT,
            reason_code  TEXT,
            raw_data     TEXT,
            rejected_at  TEXT DEFAULT (datetime('now'))
        )
    """)
    con.commit()

    print(f"Validating raw tables in {DB_PATH}\n")

    res = validate_transactions(con)
    print(f"transactions  accepted={res['accepted']:>5}  "
          f"dupes={res['dupes']}  bad_ts={res['bad_ts']}  "
          f"null_critical={res['null_critical']}  orphan={res['orphan']}  out_of_range={res['out_of_range']}")

    res = validate_products(con)
    print(f"products      accepted={res['accepted']:>5}  dupes={res['dupes']}")

    res = validate_stores(con)
    print(f"stores        accepted={res['accepted']:>5}")

    res = validate_promotions(con)
    print(f"promotions    accepted={res['accepted']:>5}  bad_dates={res['bad_dates']}  unknown_sku={res['unknown_sku']}")

    for src, dest in [
        ("raw_market_data",         "clean_market_data"),
        ("raw_marketing_spend",     "clean_marketing_spend"),
        ("raw_weather_data",        "clean_weather_data"),
        ("raw_stockout_events",     "clean_stockout_events"),
        ("raw_competitor_activity", "clean_competitor_activity"),
    ]:
        res = validate_passthrough(con, src, dest, "")
        print(f"{dest:<30} accepted={res['accepted']:>5}")

    total_rejected = cur.execute("SELECT COUNT(*) FROM rejected_records").fetchone()[0]
    print(f"\nTotal rows in rejected_records: {total_rejected}")
    print("\nValidation complete.")
    con.close()


if __name__ == "__main__":
    main()
