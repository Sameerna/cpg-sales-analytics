"""
Loads all raw CSVs into SQLite as raw.* tables.
Run: python ingestion/load_raw.py
"""
import csv
import os
import sqlite3
from pathlib import Path

DB_PATH  = os.getenv("DB_PATH", "./data/cpg.db")
RAW_DIR  = Path("data/raw")

RAW_TABLES = {
    "transactions":       RAW_DIR / "transactions.csv",
    "products":           RAW_DIR / "products.csv",
    "stores":             RAW_DIR / "stores.csv",
    "promotions":         RAW_DIR / "promotions.csv",
    "market_data":        RAW_DIR / "market_data.csv",
    "marketing_spend":    RAW_DIR / "marketing_spend.csv",
    "weather_data":       RAW_DIR / "weather_data.csv",
    "stockout_events":    RAW_DIR / "stockout_events.csv",
    "competitor_activity":RAW_DIR / "competitor_activity.csv",
}


def _create_table(cur: sqlite3.Cursor, table: str, columns: list[str]) -> None:
    cols_ddl = ", ".join(f'"{c}" TEXT' for c in columns)
    cur.execute(f'DROP TABLE IF EXISTS raw_{table}')
    cur.execute(f'CREATE TABLE raw_{table} ({cols_ddl})')


def load_csv(con: sqlite3.Connection, table: str, path: Path) -> int:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows   = list(reader)

    if not rows:
        return 0

    cur = con.cursor()
    columns = list(rows[0].keys())
    _create_table(cur, table, columns)

    placeholders = ", ".join("?" for _ in columns)
    cur.executemany(
        f'INSERT INTO raw_{table} VALUES ({placeholders})',
        [tuple(r.get(c, "") for c in columns) for r in rows],
    )
    con.commit()
    return len(rows)


def main() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)

    print(f"Loading raw CSVs into {DB_PATH}")
    for table, path in RAW_TABLES.items():
        if not path.exists():
            print(f"  SKIP  {path} (not found)")
            continue
        n = load_csv(con, table, path)
        print(f"  OK    raw_{table:<25} {n:>6} rows")

    con.close()
    print("Done.")


if __name__ == "__main__":
    main()
