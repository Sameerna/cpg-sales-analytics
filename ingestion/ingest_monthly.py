"""
Incremental monthly ingestion pipeline.

Drop a new transactions file into data/incoming/ using the naming convention:
    transactions_YYYY_MM.csv   (e.g. transactions_2026_05.csv)

Then run:
    python ingestion/ingest_monthly.py

What it does:
  1. Creates _ingestion_log in the DB (tracks every file ever processed).
  2. Skips files already in the log — safe to re-run at any time.
  3. For each new file: validates schema, appends raw rows, validates quality,
     appends clean rows, quarantines bad rows, writes log entry.
  4. Runs `dbt run` to refresh all marts with the new data.

Only transactions.csv is expected to arrive monthly. Reference tables
(products, stores, promotions, etc.) are updated via load_raw.py + validate.py
when they change.
"""
import csv
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from dateutil import parser as dateutil_parser

DB_PATH     = os.getenv("DB_PATH", "./data/cpg.db")
INCOMING    = Path("data/incoming")
DBT_PROJECT = Path("dbt_project")

# Expected columns in every incoming transactions CSV
REQUIRED_COLS = {
    "transaction_id", "timestamp", "sku_id", "store_id",
    "quantity", "unit_price", "channel",
}

VALID_CHANNELS = {"pos", "online"}


# ── helpers ───────────────────────────────────────────────────────────────────

def _parse_filename(name: str) -> Optional[tuple[int, int]]:
    """Return (year, month) from 'transactions_YYYY_MM.csv', else None."""
    m = re.fullmatch(r"transactions_(\d{4})_(\d{2})\.csv", name)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _parse_timestamp(raw: str) -> Optional[str]:
    raw = raw.strip()
    try:
        if raw.isdigit():
            return datetime.fromtimestamp(int(raw)).isoformat()
        return dateutil_parser.parse(raw).isoformat()
    except Exception:
        return None


def _ensure_schema(con: sqlite3.Connection) -> None:
    """Create supporting tables if they don't exist yet."""
    cur = con.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS _ingestion_log (
            filename        TEXT PRIMARY KEY,
            year            INTEGER,
            month           INTEGER,
            rows_raw        INTEGER,
            rows_clean      INTEGER,
            rows_rejected   INTEGER,
            loaded_at       TEXT DEFAULT (datetime('now'))
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS rejected_records (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            source_table    TEXT,
            row_identifier  TEXT,
            reason_code     TEXT,
            raw_data        TEXT,
            rejected_at     TEXT DEFAULT (datetime('now'))
        )
    """)

    # raw_transactions — append-only; created on first load if absent
    cur.execute("""
        CREATE TABLE IF NOT EXISTS raw_transactions (
            transaction_id TEXT,
            timestamp      TEXT,
            sku_id         TEXT,
            store_id       TEXT,
            quantity       TEXT,
            unit_price     TEXT,
            channel        TEXT,
            customer_id    TEXT
        )
    """)

    # clean_transactions — append-only; PRIMARY KEY guards against duplicates
    cur.execute("""
        CREATE TABLE IF NOT EXISTS clean_transactions (
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

    con.commit()


def _already_processed(cur: sqlite3.Cursor, filename: str) -> bool:
    row = cur.execute(
        "SELECT 1 FROM _ingestion_log WHERE filename = ?", (filename,)
    ).fetchone()
    return row is not None


# ── per-file pipeline ──────────────────────────────────────────────────────────

def _load_raw(con: sqlite3.Connection, path: Path, filename: str) -> list[dict]:
    """Append raw rows to raw_transactions; return the list for validation."""
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        return []

    actual_cols = set(rows[0].keys())
    missing = REQUIRED_COLS - actual_cols
    if missing:
        raise ValueError(f"Missing required columns in {filename}: {missing}")

    cur = con.cursor()
    cur.executemany(
        """
        INSERT INTO raw_transactions
            (transaction_id, timestamp, sku_id, store_id,
             quantity, unit_price, channel, customer_id)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        [
            (
                r.get("transaction_id", ""),
                r.get("timestamp", ""),
                r.get("sku_id", ""),
                r.get("store_id", ""),
                r.get("quantity", ""),
                r.get("unit_price", ""),
                r.get("channel", ""),
                r.get("customer_id", ""),
            )
            for r in rows
        ],
    )
    con.commit()
    return rows


def _validate_and_append(con: sqlite3.Connection, rows: list[dict]) -> dict:
    """
    Validate rows against quality rules and against existing clean_transactions.
    Appends clean rows; quarantines bad rows. Returns counts.
    """
    cur = con.cursor()

    valid_stores = {
        r[0] for r in cur.execute("SELECT store_id FROM raw_stores").fetchall()
    }
    existing_ids = {
        r[0] for r in cur.execute("SELECT transaction_id FROM clean_transactions").fetchall()
    }

    seen_in_file: set[str] = set()
    clean_rows: list[tuple] = []
    rejected = dupes = bad_ts = null_critical = out_of_range = orphan = 0

    for row in rows:
        tid = row.get("transaction_id", "")

        if tid in existing_ids or tid in seen_in_file:
            _quarantine(cur, "transactions", tid, "DUPLICATE_TXN_ID", row)
            dupes += 1
            continue
        seen_in_file.add(tid)

        ts = _parse_timestamp(row.get("timestamp", ""))
        if not ts:
            _quarantine(cur, "transactions", tid, "UNPARSEABLE_TIMESTAMP", row)
            bad_ts += 1
            continue

        if not row.get("quantity") or not row.get("unit_price"):
            _quarantine(cur, "transactions", tid, "NULL_CRITICAL_FIELD", row)
            null_critical += 1
            continue

        try:
            qty = int(row["quantity"])
            if qty <= 0:
                raise ValueError
        except ValueError:
            _quarantine(cur, "transactions", tid, "INVALID_QUANTITY", row)
            out_of_range += 1
            continue

        try:
            price = float(row["unit_price"])
            if price <= 0:
                raise ValueError
        except ValueError:
            _quarantine(cur, "transactions", tid, "INVALID_PRICE", row)
            null_critical += 1
            continue

        if row.get("store_id") not in valid_stores:
            _quarantine(cur, "transactions", tid, "ORPHAN_STORE_ID", row)
            orphan += 1
            continue

        ch = row.get("channel", "").strip().lower()
        ch_norm = ch if ch in VALID_CHANNELS else "unknown"

        clean_rows.append((
            tid, ts,
            row.get("sku_id") or None,
            row.get("store_id"),
            qty, price, ch_norm,
            row.get("customer_id") or None,
        ))

    if clean_rows:
        cur.executemany(
            "INSERT OR IGNORE INTO clean_transactions VALUES (?,?,?,?,?,?,?,?)",
            clean_rows,
        )

    con.commit()
    rejected = dupes + bad_ts + null_critical + out_of_range + orphan
    return {
        "accepted": len(clean_rows),
        "rejected": rejected,
        "dupes": dupes,
        "bad_ts": bad_ts,
        "null_critical": null_critical,
        "out_of_range": out_of_range,
        "orphan": orphan,
    }


def _quarantine(
    cur: sqlite3.Cursor,
    source: str,
    row_id: str,
    reason: str,
    row: dict,
) -> None:
    cur.execute(
        """
        INSERT INTO rejected_records (source_table, row_identifier, reason_code, raw_data)
        VALUES (?, ?, ?, ?)
        """,
        (source, row_id, reason, json.dumps(row)),
    )


def _write_log(
    cur: sqlite3.Cursor,
    filename: str,
    year: int,
    month: int,
    rows_raw: int,
    rows_clean: int,
    rows_rejected: int,
) -> None:
    cur.execute(
        """
        INSERT INTO _ingestion_log
            (filename, year, month, rows_raw, rows_clean, rows_rejected)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (filename, year, month, rows_raw, rows_clean, rows_rejected),
    )


# ── dbt refresh ───────────────────────────────────────────────────────────────

def _run_dbt() -> bool:
    """Run `dbt run` from the dbt_project directory. Returns True on success."""
    print("\nRunning dbt to refresh marts...")
    result = subprocess.run(
        ["dbt", "run"],
        cwd=str(DBT_PROJECT),
        capture_output=False,
    )
    return result.returncode == 0


# ── orchestrator ──────────────────────────────────────────────────────────────

def main(run_dbt: bool = True) -> None:
    if not INCOMING.exists():
        print(f"Incoming directory not found: {INCOMING}")
        print("Create it and place transaction CSVs there.")
        sys.exit(1)

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    _ensure_schema(con)

    csv_files = sorted(INCOMING.glob("transactions_*.csv"))
    if not csv_files:
        print(f"No transaction files found in {INCOMING}/")
        print("Expected format: transactions_YYYY_MM.csv")
        con.close()
        return

    processed = 0
    for path in csv_files:
        filename = path.name
        parsed = _parse_filename(filename)

        if parsed is None:
            print(f"  SKIP  {filename} — does not match transactions_YYYY_MM.csv")
            continue

        if _already_processed(cur, filename):
            print(f"  SKIP  {filename} — already in ingestion log")
            continue

        year, month = parsed
        print(f"  LOAD  {filename}  ({year}-{month:02d})")

        try:
            raw_rows = _load_raw(con, path, filename)
        except ValueError as e:
            print(f"  ERROR {filename} — {e}")
            continue

        stats = _validate_and_append(con, raw_rows)
        _write_log(cur, filename, year, month,
                   len(raw_rows), stats["accepted"], stats["rejected"])
        con.commit()

        print(
            f"         raw={len(raw_rows)}  "
            f"clean={stats['accepted']}  "
            f"rejected={stats['rejected']} "
            f"(dupes={stats['dupes']} bad_ts={stats['bad_ts']} "
            f"null={stats['null_critical']} range={stats['out_of_range']} "
            f"orphan={stats['orphan']})"
        )
        processed += 1

    con.close()

    if processed == 0:
        print("\nNo new files to process.")
        return

    print(f"\n{processed} file(s) ingested.")

    if run_dbt:
        ok = _run_dbt()
        if ok:
            print("dbt run complete. All marts refreshed.")
        else:
            print("dbt run failed — check dbt output above.")
            sys.exit(1)
    else:
        print("Skipping dbt run (pass --no-dbt to suppress, or remove flag to run).")


if __name__ == "__main__":
    run_dbt = "--no-dbt" not in sys.argv
    main(run_dbt=run_dbt)
