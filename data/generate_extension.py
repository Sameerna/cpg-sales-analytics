#!/usr/bin/env python3
"""
Generate 2025 + 2026 Jan-Apr extension data for CPG Sales Analytics.

Story arcs encoded:
  Beverages   — temperature-driven summer spike (Jun-Aug); RivalCo pressure in APAC
  Snacks      — price hike Apr 2025 → elastic demand dip; recovery Q4
  Dairy       — price-inelastic, steady growth (+20% YoY)
  Personal Care — market share gains, premium segment
  Household   — volume leader, Tier A/B stores dominant
  Digital     — growing from 48% → 58% of marketing budget by 2025
  Store tiers — Tier A +72%, Tier B +79%, Tier C losing share
  Customers   — top 10% (CUST00001-CUST00450) = ~30% of revenue
  Q4 2025     — strong seasonal peak; stockout cluster
  2026 Jan-Apr — recovery trend, Beverages rebounds
"""

import csv
import math
import random
import sqlite3
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

random.seed(42)
DATA_DIR = Path("data/raw")
DB_PATH  = "./data/cpg.db"

CATEGORIES = ["Beverages", "Snacks", "Dairy", "Personal Care", "Household"]
REGIONS    = ["North", "South", "East", "West"]
CHANNELS   = ["digital", "tv", "in_store"]

# ─── Reference data ────────────────────────────────────────────────────────────

def load_ref(db_path: str) -> dict:
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    # SKUs by normalised category
    cur.execute("SELECT sku_id, category FROM clean_products")
    cat_skus: Dict[str, List[str]] = {}
    for sku, cat in cur.fetchall():
        c = cat.strip().title()
        # Normalise "Personal Care" vs "Personal care"
        if "personal" in c.lower():
            c = "Personal Care"
        cat_skus.setdefault(c, []).append(sku)

    # Stores with clean region
    region_norm = {
        "north": "North", "south": "South", "east": "East", "west": "West",
        "n": "North", "s": "South", "e": "East", "w": "West",
        "north region": "North", "south region": "South",
        "east region": "East",  "west region": "West",
    }
    cur.execute("SELECT store_id, region, store_tier FROM clean_stores")
    stores: List[dict] = []
    for sid, reg, tier in cur.fetchall():
        r = region_norm.get(reg.lower().strip(), reg.strip())
        t = tier.strip() if tier else "B"
        stores.append({"id": sid, "region": r, "tier": t})

    # Max IDs
    cur.execute("SELECT MAX(CAST(REPLACE(transaction_id,'TXN','') AS INTEGER)) "
                "FROM clean_transactions WHERE transaction_id LIKE 'TXN%'")
    max_txn = (cur.fetchone()[0] or 50000) + 1

    cur.execute("SELECT MAX(CAST(REPLACE(customer_id,'CUST','') AS INTEGER)) "
                "FROM clean_transactions WHERE customer_id LIKE 'CUST%'")
    max_cust = cur.fetchone()[0] or 4000

    # 2024 market revenue baseline (per quarter, category, region)
    cur.execute("""
        SELECT year, quarter, category, region, total_market_revenue_usd
        FROM clean_market_data WHERE year='2024'
    """)
    mkt_2024: Dict[Tuple, float] = {}
    for yr, q, cat, reg, rev in cur.fetchall():
        c = cat.strip().title()
        if "personal" in c.lower():
            c = "Personal Care"
        r = region_norm.get(reg.lower().strip(), reg.strip())
        mkt_2024[(str(q), c, r)] = float(rev or 0)

    # 2024 marketing spend baseline
    cur.execute("""
        SELECT month, category, channel, AVG(CAST(spend_usd AS REAL))
        FROM clean_marketing_spend WHERE year='2024'
        GROUP BY month, category, channel
    """)
    spend_2024: Dict[Tuple, float] = {}
    for mo, cat, ch, spend in cur.fetchall():
        c = cat.strip().title()
        if "personal" in c.lower():
            c = "Personal Care"
        spend_2024[(int(mo), c, ch)] = float(spend or 0)

    # 2024 weather baseline
    cur.execute("""
        SELECT month, region, avg_temp_celsius, rainfall_mm, heat_index
        FROM clean_weather_data WHERE year='2024'
    """)
    weather_2024: Dict[Tuple, tuple] = {}
    for mo, reg, temp, rain, hi in cur.fetchall():
        r = region_norm.get(reg.lower().strip(), reg.strip())
        weather_2024[(int(mo), r)] = (float(temp or 0), float(rain or 50), float(hi or 0))

    # Max promo ID — read from raw CSV to avoid off-by-one with rejected rows
    max_promo = 850
    promo_csv = Path("data/raw/promotions.csv")
    if promo_csv.exists():
        with open(promo_csv, newline="") as f:
            for row in csv.DictReader(f):
                pid = row.get("promo_id", "")
                if pid.startswith("PROMO"):
                    try:
                        max_promo = max(max_promo, int(pid.replace("PROMO", "")))
                    except ValueError:
                        pass
    n_promos = max_promo

    # Max competitor event
    cur.execute("SELECT COUNT(*) FROM clean_competitor_activity")
    n_ce = cur.fetchone()[0] or 10

    con.close()
    return {
        "cat_skus": cat_skus,
        "stores": stores,
        "max_txn": max_txn,
        "max_cust": max_cust,
        "mkt_2024": mkt_2024,
        "spend_2024": spend_2024,
        "weather_2024": weather_2024,
        "n_promos": n_promos,
        "n_ce": n_ce,
    }

# ─── Seasonality helpers ───────────────────────────────────────────────────────

# Monthly volume multiplier (1.0 = avg month in 2024)
MONTHLY_VOL = {
    1: 0.85, 2: 0.82, 3: 0.98, 4: 1.02, 5: 1.00, 6: 1.05,
    7: 1.10, 8: 1.08, 9: 0.98, 10: 1.02, 11: 1.15, 12: 1.40,
}
# Beverages gets an extra summer boost (temperature effect)
BEV_SUMMER_BOOST = {6: 1.30, 7: 1.40, 8: 1.38, 9: 1.10}

# Snacks price hike in Apr-Jun 2025 → volume dip
SNACKS_HIKE_MONTHS_2025 = {4, 5, 6}
SNACKS_HIKE_VOL_FACTOR  = 0.84  # -16% volume during hike

# Unit price baselines per category (2024 avg from DB) with 2025/2026 inflation
PRICE_BASE = {
    "Beverages":    5.41,
    "Snacks":       2.94,
    "Dairy":        4.00,
    "Personal Care":19.82,
    "Household":    14.26,
}
# Annual price inflation
PRICE_INFLATION = {"2025": 1.05, "2026": 1.10}
# Snacks extra price hike (Apr 2025 onward, partial recovery in Q4)
SNACKS_HIKE_FACTOR = {"hike": 1.28, "recovery": 1.18}

# Average quantity per transaction per category
QTY_MEAN = {
    "Beverages":    14, "Snacks":       14, "Dairy":        13,
    "Personal Care":14, "Household":    14,
}

# Category share of total transactions (must sum to 1)
CAT_SHARE = {
    "Beverages":    0.21, "Snacks":    0.18, "Dairy":        0.19,
    "Personal Care":0.18, "Household": 0.24,
}
# Beverages summer share spike (replace other categories proportionally in summer)
BEV_SUMMER_SHARE_BOOST = {6: 0.04, 7: 0.06, 8: 0.05}

# Channel mix evolution: online share
ONLINE_SHARE = {"2025": 0.36, "2026": 0.40}

# Store tier transaction weights
TIER_WEIGHTS = {"A": 4.0, "B": 3.0, "C": 1.0}

# Power customer concentration: top CUST00001-CUST00450 get 30% of txns
POWER_CUST_THRESHOLD = 450
POWER_CUST_SHARE     = 0.30

def pick_category(month: int, year: str, snacks_hike: bool) -> str:
    """Draw a category weighted by share + seasonal adjustments."""
    shares = dict(CAT_SHARE)
    # Summer: boost Beverages, reduce others proportionally
    bev_boost = BEV_SUMMER_SHARE_BOOST.get(month, 0)
    if bev_boost > 0:
        shares["Beverages"] += bev_boost
        reduction_per = bev_boost / (len(CATEGORIES) - 1)
        for c in CATEGORIES:
            if c != "Beverages":
                shares[c] = max(0.01, shares[c] - reduction_per)
    cats  = list(shares.keys())
    wts   = [shares[c] for c in cats]
    total = sum(wts)
    r = random.random() * total
    cum = 0.0
    for c, w in zip(cats, wts):
        cum += w
        if r <= cum:
            return c
    return "Household"

def pick_price(cat: str, year: str, month: int) -> float:
    base = PRICE_BASE[cat] * PRICE_INFLATION.get(year, 1.0)
    if cat == "Snacks":
        if year == "2025" and month in SNACKS_HIKE_MONTHS_2025:
            base *= SNACKS_HIKE_FACTOR["hike"]
        elif year == "2025" and month > 6:
            base *= SNACKS_HIKE_FACTOR["recovery"]
        elif year == "2026":
            base *= SNACKS_HIKE_FACTOR["recovery"]
    noise = random.gauss(1.0, 0.12)
    return round(max(0.50, base * noise), 2)

def pick_qty(cat: str) -> int:
    mean = QTY_MEAN[cat]
    qty  = max(1, int(random.gauss(mean, mean * 0.35)))
    return min(qty, 50)

def pick_customer(max_cust: int) -> str:
    if random.random() < POWER_CUST_SHARE:
        cid = random.randint(1, POWER_CUST_THRESHOLD)
    else:
        cid = random.randint(POWER_CUST_THRESHOLD + 1, max_cust)
    return f"CUST{cid:05d}"

def pick_store(stores: List[dict], region: str) -> str:
    regional = [s for s in stores if s["region"] == region]
    if not regional:
        regional = stores
    weights = [TIER_WEIGHTS.get(s["tier"], 2.0) for s in regional]
    total = sum(weights)
    r = random.random() * total
    cum = 0.0
    for s, w in zip(regional, weights):
        cum += w
        if r <= cum:
            return s["id"]
    return regional[0]["id"]

def pick_region(cat: str, year: str, month: int) -> str:
    """RivalCo in APAC/East lowers Beverages volume there."""
    if cat == "Beverages" and year in ("2025", "2026"):
        # East (APAC) slightly suppressed due to RivalCo
        weights = {"North": 0.30, "South": 0.26, "East": 0.22, "West": 0.22}
    else:
        weights = {"North": 0.30, "South": 0.26, "East": 0.24, "West": 0.20}
    regions = list(weights.keys())
    wts = [weights[r] for r in regions]
    total = sum(wts)
    r_ = random.random() * total
    cum = 0.0
    for reg, w in zip(regions, wts):
        cum += w
        if r_ <= cum:
            return reg
    return "North"

# ─── Transaction generation ────────────────────────────────────────────────────

def gen_transactions(ref: dict) -> List[dict]:
    """Generate transactions for 2025-01 to 2026-04."""
    rows = []
    txn_counter = ref["max_txn"]

    # Monthly targets (base from 2024 avg ~1,213)
    monthly_targets = {
        (2025,  1): 1100, (2025,  2): 1060, (2025,  3): 1340,
        (2025,  4): 1370, (2025,  5): 1340, (2025,  6): 1450,
        (2025,  7): 1530, (2025,  8): 1500, (2025,  9): 1370,
        (2025, 10): 1430, (2025, 11): 1570, (2025, 12): 1780,
        (2026,  1): 1200, (2026,  2): 1260, (2026,  3): 1490,
        (2026,  4): 1510,
    }

    for (yr, mo), n_target in monthly_targets.items():
        year_str = str(yr)
        # Spread transactions across the month
        days_in_month = [date(yr, mo, d)
                         for d in range(1, 29 if mo == 2
                                        else 31 if mo in (1,3,5,7,8,10,12)
                                        else 30 + 1)]
        days_in_month = [d for d in days_in_month if d.month == mo]

        for _ in range(n_target):
            cat   = pick_category(mo, year_str, mo in SNACKS_HIKE_MONTHS_2025 and yr == 2025)
            # Apply Snacks hike volume suppression
            if cat == "Snacks" and yr == 2025 and mo in SNACKS_HIKE_MONTHS_2025:
                if random.random() > SNACKS_HIKE_VOL_FACTOR:
                    cat = pick_category(mo, year_str, False)

            region  = pick_region(cat, year_str, mo)
            store   = pick_store(ref["stores"], region)
            qty     = pick_qty(cat)
            price   = pick_price(cat, year_str, mo)
            channel = "online" if random.random() < ONLINE_SHARE.get(year_str, 0.31) else "pos"
            cust    = pick_customer(ref["max_cust"])

            skus = ref["cat_skus"].get(cat, [])
            if not skus:
                # fallback — use any sku
                all_skus = [s for ss in ref["cat_skus"].values() for s in ss]
                sku = random.choice(all_skus)
            else:
                sku = random.choice(skus)

            # Random time during the day, weighted to business hours
            day = random.choice(days_in_month)
            hour = random.choices(
                range(24),
                weights=[1,1,0,0,0,1,3,6,9,10,10,10,9,8,9,10,10,9,8,7,6,5,4,2],
                k=1
            )[0]
            minute = random.randint(0, 59)
            second = random.randint(0, 59)
            ts = datetime(yr, mo, day.day, hour, minute, second).isoformat()

            txn_counter += 1
            rows.append({
                "transaction_id": f"TXN{txn_counter:07d}",
                "timestamp":      ts,
                "sku_id":         sku,
                "store_id":       store,
                "quantity":       qty,
                "unit_price":     price,
                "channel":        channel,
                "customer_id":    cust,
            })

    print(f"  transactions: {len(rows)} rows generated")
    return rows

# ─── Market data ───────────────────────────────────────────────────────────────

def gen_market_data(ref: dict) -> List[dict]:
    """
    Market growing ~30% YoY.
    Company GAINING share in Household (+2pp/yr) and Personal Care (+1.5pp/yr).
    Company LOSING share in Beverages (-1pp/yr RivalCo) and Snacks (-0.5pp/yr).
    Dairy roughly flat share.
    """
    rows: List[dict] = []
    mkt_2024 = ref["mkt_2024"]

    # Annual market growth factor (total market)
    MKT_GROWTH = {"2025": 1.30, "2026": 1.30}
    # Q-within-year seasonal weights (revenue skewed to Q4)
    Q_WEIGHT = {1: 0.22, 2: 0.24, 3: 0.25, 4: 0.29}

    # Compute 2024 annual total per category-region to get 2025 annual totals
    # then split by quarter
    cat_reg_2024_annual: Dict[Tuple, float] = {}
    for (q, cat, reg), rev in mkt_2024.items():
        key = (cat, reg)
        cat_reg_2024_annual[key] = cat_reg_2024_annual.get(key, 0) + rev

    for yr_str, mkt_growth in MKT_GROWTH.items():
        yr = int(yr_str)
        quarters = [1, 2, 3, 4] if yr == 2025 else [1]

        for q in quarters:
            for cat in CATEGORIES:
                for reg in REGIONS:
                    base = cat_reg_2024_annual.get((cat, reg), 150000)
                    # Apply multi-year growth
                    years_from_2024 = yr - 2024
                    annual_rev = base * (mkt_growth ** years_from_2024)
                    q_rev = annual_rev * Q_WEIGHT[q]
                    # Add noise
                    q_rev *= random.gauss(1.0, 0.04)
                    period = f"{yr}-Q{q}"
                    rows.append({
                        "period": period, "year": yr_str, "quarter": q,
                        "category": cat, "region": reg,
                        "total_market_revenue_usd": round(q_rev),
                        "data_source": "NielsenIQ Syndicated Panel",
                    })

    print(f"  market_data: {len(rows)} rows generated")
    return rows

# ─── Marketing spend ──────────────────────────────────────────────────────────

def gen_marketing_spend(ref: dict) -> List[dict]:
    """
    Digital: 48% (2024) → 58% (2025) → 65% (2026) of total budget.
    Total budget growing ~18% YoY.
    Impressions on digital growing faster (programmatic efficiencies).
    """
    rows: List[dict] = []
    spend_2024 = ref["spend_2024"]

    # 2024 average spend per channel (across all categories/months)
    channel_share_2025 = {"digital": 0.58, "tv": 0.24, "in_store": 0.18}
    channel_share_2026 = {"digital": 0.65, "tv": 0.20, "in_store": 0.15}

    # CPM (cost per 1000 impressions) by channel - digital improving
    cpm = {"2025": {"digital": 7.50, "tv": 27.00, "in_store": 0.0},
           "2026": {"digital": 6.80, "tv": 26.00, "in_store": 0.0}}

    periods = [(2025, mo) for mo in range(1, 13)] + [(2026, mo) for mo in range(1, 5)]

    for yr, mo in periods:
        yr_str = str(yr)
        ch_share = channel_share_2025 if yr == 2025 else channel_share_2026
        budget_growth = 1.18 if yr == 2025 else 1.18 * 1.15

        for cat in CATEGORIES:
            total_2024 = sum(spend_2024.get((mo, cat, ch), 5000) for ch in CHANNELS)
            total_budget = total_2024 * budget_growth * random.gauss(1.0, 0.06)

            for ch in CHANNELS:
                spend = total_budget * ch_share[ch]
                if ch == "digital":
                    impr = int(spend / cpm[yr_str]["digital"] * 1000 * random.gauss(1.0, 0.08))
                    active = "Y"
                elif ch == "tv":
                    impr = int(spend / cpm[yr_str]["tv"] * 1000 * random.gauss(1.0, 0.1)) if spend > 0 else 0
                    active = "Y" if random.random() > 0.15 else "N"
                else:  # in_store
                    impr = 0
                    active = "Y"

                period = f"{yr}-{mo:02d}"
                rows.append({
                    "period": period, "year": yr_str, "month": mo,
                    "category": cat, "channel": ch,
                    "spend_usd": round(spend, 2),
                    "impressions": max(0, impr),
                    "campaign_active": active,
                })

    print(f"  marketing_spend: {len(rows)} rows generated")
    return rows

# ─── Weather data ─────────────────────────────────────────────────────────────

def gen_weather(ref: dict) -> List[dict]:
    """
    Seasonal temperature profiles per region.
    2025 is slightly warmer (+0.8°C avg) vs 2024 — useful for Beverages correlation.
    """
    rows: List[dict] = []
    weather_2024 = ref["weather_2024"]

    # Base temperature profiles (monthly, North = reference)
    TEMP_NORTH  = [3.7, 4.5, 8.2, 13.8, 18.9, 24.1, 28.0, 27.4, 21.3, 14.2, 7.6, 3.2]
    TEMP_OFFSET = {"North": 0, "South": 7.0, "East": 5.0, "West": 3.0}
    RAIN_NORTH  = [55, 50, 62, 55, 48, 33, 24, 29, 46, 62, 68, 58]
    RAIN_OFFSET = {"North": 0, "South": 15, "East": 20, "West": -5}

    # 2025 slightly warmer
    warming = {"2025": 0.8, "2026": 1.1}

    periods = [(2025, mo) for mo in range(1, 13)] + [(2026, mo) for mo in range(1, 5)]

    for yr, mo in periods:
        yr_str = str(yr)
        for reg in REGIONS:
            base_temp = TEMP_NORTH[mo - 1] + TEMP_OFFSET[reg] + warming.get(yr_str, 0)
            temp = round(base_temp + random.gauss(0, 0.5), 1)
            rain = max(0, RAIN_NORTH[mo - 1] + RAIN_OFFSET[reg] + random.gauss(0, 8))
            heat_idx = round(temp + (2.5 if mo in (6, 7, 8) else 0.5), 1)
            period = f"{yr}-{mo:02d}"
            rows.append({
                "period": period, "year": yr_str, "month": mo,
                "region": reg,
                "avg_temp_celsius": temp,
                "rainfall_mm": round(rain, 1),
                "heat_index": heat_idx,
            })

    print(f"  weather_data: {len(rows)} rows generated")
    return rows

# ─── Promotions ───────────────────────────────────────────────────────────────

def gen_promotions(ref: dict) -> List[dict]:
    """
    2025-2026 promotions.
    Key themes:
    - Defensive Beverages promos in APAC (Q2-Q3 2025) vs RivalCo
    - Snacks loyalty discounts in Q3 2025 (post-hike recovery push)
    - Q4 2025 broad holiday promotions
    - Premium Personal Care launches in 2026
    """
    rows: List[dict] = []
    counter = ref["n_promos"] + 1

    # Load valid SKUs per category for promotion targeting
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT sku_id, category FROM clean_products")
    cat_skus_: Dict[str, List[str]] = {}
    for sku, cat in cur.fetchall():
        c = cat.strip().title()
        if "personal" in c.lower():
            c = "Personal Care"
        cat_skus_.setdefault(c, []).append(sku)
    con.close()

    # Promo schedule: (cat, start_mo, start_yr, duration_days, discount_range, channel, count)
    promo_batches = [
        # Beverages APAC push vs RivalCo
        ("Beverages",    4, 2025, 60, (10, 18), "online",  12),
        ("Beverages",    7, 2025, 45, (12, 20), "online",   8),
        # Snacks recovery push (post price hike)
        ("Snacks",       7, 2025, 90, (15, 25), "all",     15),
        ("Snacks",      10, 2025, 60, (12, 18), "all",     10),
        # Q4 2025 holiday broad push
        ("Beverages",   10, 2025, 75, ( 8, 15), "all",     20),
        ("Dairy",       10, 2025, 75, ( 5, 12), "all",     18),
        ("Household",   10, 2025, 75, ( 6, 14), "all",     22),
        ("Personal Care", 10, 2025, 60, (8, 16), "all",    15),
        ("Snacks",      10, 2025, 75, (10, 20), "all",     15),
        # 2025 mid-year general
        ("Dairy",        3, 2025, 45, ( 5, 10), "all",     12),
        ("Personal Care", 2, 2025, 30, (10, 18), "digital",10),
        ("Household",    5, 2025, 60, ( 7, 14), "in_store",14),
        # 2026 Q1 launches
        ("Personal Care", 1, 2026, 45, (12, 20), "digital",12),
        ("Beverages",    2, 2026, 60, ( 8, 15), "all",     14),
        ("Snacks",       2, 2026, 45, (10, 18), "all",     10),
        ("Dairy",        1, 2026, 30, ( 5, 10), "all",     10),
        ("Household",    3, 2026, 45, ( 6, 12), "in_store",12),
    ]

    for cat, start_mo, start_yr, duration, disc_range, channel, count in promo_batches:
        skus = cat_skus_.get(cat, [])
        if not skus:
            continue
        for i in range(count):
            sku = random.choice(skus)
            start = date(start_yr, start_mo, random.randint(1, 15))
            end   = start + timedelta(days=duration + random.randint(-10, 10))
            disc  = round(random.uniform(*disc_range), 1)
            rows.append({
                "promo_id":    f"PROMO{counter:04d}",
                "sku_id":      sku,
                "category":    cat,
                "start_date":  str(start),
                "end_date":    str(end),
                "discount_pct": disc,
                "channel":     channel,
            })
            counter += 1

    print(f"  promotions: {len(rows)} rows generated")
    return rows

# ─── Competitor activity ───────────────────────────────────────────────────────

def gen_competitor_activity(ref: dict) -> List[dict]:
    counter = ref["n_ce"] + 1
    events = [
        ("CE{:03d}", "RivalCo",    "market_entry", "Personal Care", "East",  "2025-02-01",
         "RivalCo launched 8 Personal Care SKUs in APAC targeting urban millennials at -12% vs category average"),
        ("CE{:03d}", "RivalCo",    "price_cut",    "Beverages",    "South",  "2025-04-01",
         "RivalCo cut Beverages prices 10% in LATAM to defend share after Company Q1 gains"),
        ("CE{:03d}", "ValueBrand", "online_launch","Snacks",       "All",    "2025-05-15",
         "ValueBrand launched D2C Snacks subscription box nationally competing on value during Company price hike period"),
        ("CE{:03d}", "RivalCo",    "promotion",    "Personal Care","North",  "2025-08-01",
         "RivalCo back-to-school Personal Care promo: BOGO on 6 hero SKUs in NA and EMEA"),
        ("CE{:03d}", "HealthFirst","market_entry", "Beverages",    "West",   "2025-10-01",
         "HealthFirst entered functional Beverages in EMEA with 15 wellness SKUs priced at premium"),
        ("CE{:03d}", "RivalCo",    "price_cut",    "Beverages",    "East",   "2026-01-15",
         "RivalCo aggressive New Year pricing on Beverages in APAC: -18% vs shelf for 6 weeks"),
        ("CE{:03d}", "ValueBrand", "promotion",    "Household",    "South",  "2026-03-01",
         "ValueBrand spring Household promotion in LATAM — 20% off on digital channel for 8 weeks"),
    ]
    rows = []
    for i, (_, comp, etype, cat, reg, dt, desc) in enumerate(events):
        rows.append({
            "event_id":    f"CE{counter:03d}",
            "competitor":  comp,
            "event_type":  etype,
            "category":    cat,
            "region":      reg,
            "event_date":  dt,
            "description": desc,
        })
        counter += 1
    print(f"  competitor_activity: {len(rows)} rows generated")
    return rows

# ─── Stockout events ──────────────────────────────────────────────────────────

def gen_stockout_events(ref: dict) -> List[dict]:
    """
    Q4 2025 cluster (demand spike + logistics) + LATAM logistics chain ongoing.
    Also some 2026 Q1 post-holiday supplier delays.
    """
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT sku_id FROM clean_products")
    all_skus = [r[0] for r in cur.fetchall()]
    con.close()

    events = [
        # Q4 2025 holiday cluster
        ("SKU0042", "North", "2025-10-14", "2025-10-28", 14, "demand_spike",    4820),
        ("SKU0119", "East",  "2025-10-20", "2025-11-06", 17, "supplier_delay",  6340),
        ("SKU0205", "South", "2025-10-25", "2025-11-18", 24, "logistics",       8910),
        ("SKU0311", "West",  "2025-11-02", "2025-11-22", 20, "demand_spike",    5620),
        ("SKU0087", "All",   "2025-11-08", "2025-12-04", 26, "demand_spike",    9240),
        ("SKU0174", "East",  "2025-11-15", "2025-12-10", 25, "logistics",       7100),
        ("SKU0261", "South", "2025-11-20", "2025-12-15", 25, "logistics",      11400),
        ("SKU0344", "North", "2025-12-01", "2025-12-14", 13, "quality_hold",    3870),
        ("SKU0058", "West",  "2025-12-05", "2025-12-22", 17, "supplier_delay",  5900),
        # LATAM ongoing logistics issues
        ("SKU0133", "South", "2025-06-10", "2025-07-05", 25, "logistics",       7650),
        ("SKU0198", "South", "2025-08-12", "2025-09-04", 23, "logistics",       6820),
        # 2026 Q1 post-holiday supplier delays
        ("SKU0075", "East",  "2026-01-08", "2026-01-25", 17, "supplier_delay",  4120),
        ("SKU0322", "All",   "2026-02-14", "2026-03-03", 17, "demand_spike",    5480),
        ("SKU0163", "North", "2026-03-18", "2026-04-04", 17, "logistics",       3950),
    ]
    rows = []
    for sku, reg, start, end, days, reason, lost in events:
        rows.append({
            "sku_id":                    sku,
            "region":                    reg,
            "stockout_start":            start,
            "stockout_end":              end,
            "duration_days":             days,
            "reason":                    reason,
            "estimated_lost_revenue_usd": lost,
        })
    print(f"  stockout_events: {len(rows)} rows generated")
    return rows

# ─── CSV append helpers ────────────────────────────────────────────────────────

def append_csv(path: Path, new_rows: List[dict]) -> None:
    if not new_rows:
        return
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(new_rows[0].keys()))
        writer.writerows(new_rows)

def read_headers(path: Path) -> List[str]:
    with open(path, newline="", encoding="utf-8") as f:
        return next(csv.reader(f))

# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("Loading reference data from DB…")
    ref = load_ref(DB_PATH)
    print(f"  SKU categories: {list(ref['cat_skus'].keys())}")
    print(f"  Stores: {len(ref['stores'])}")
    print(f"  Max TXN ID: {ref['max_txn']}")
    print()

    print("Generating extension data…")
    txn_rows  = gen_transactions(ref)
    mkt_rows  = gen_market_data(ref)
    spend_rows= gen_marketing_spend(ref)
    wx_rows   = gen_weather(ref)
    promo_rows= gen_promotions(ref)
    comp_rows = gen_competitor_activity(ref)
    stock_rows= gen_stockout_events(ref)
    print()

    print("Appending to CSVs…")
    append_csv(DATA_DIR / "transactions.csv",      txn_rows)
    append_csv(DATA_DIR / "market_data.csv",       mkt_rows)
    append_csv(DATA_DIR / "marketing_spend.csv",   spend_rows)
    append_csv(DATA_DIR / "weather_data.csv",      wx_rows)
    append_csv(DATA_DIR / "promotions.csv",        promo_rows)
    append_csv(DATA_DIR / "competitor_activity.csv", comp_rows)
    append_csv(DATA_DIR / "stockout_events.csv",   stock_rows)
    print("  Done.")
    print()

    print("Re-running ingestion pipeline…")
    r = subprocess.run([sys.executable, "ingestion/load_raw.py"], capture_output=True, text=True)
    print(r.stdout.strip())
    if r.returncode != 0:
        print("ERROR:", r.stderr)
        sys.exit(1)

    r = subprocess.run([sys.executable, "ingestion/validate.py"], capture_output=True, text=True)
    print(r.stdout.strip())
    if r.returncode != 0:
        print("ERROR:", r.stderr)
        sys.exit(1)

    print()
    print("Re-running dbt…")
    r = subprocess.run(
        ["python3", "-m", "dbt", "run", "--project-dir", "dbt_project",
         "--profiles-dir", "dbt_project"],
        capture_output=True, text=True
    )
    print(r.stdout[-2000:] if len(r.stdout) > 2000 else r.stdout)
    if r.returncode != 0:
        print("STDERR:", r.stderr[-1000:])
        sys.exit(1)

    print()
    print("Verifying row counts in marts…")
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    for tbl in ["mart_forecast_inputs", "mart_revenue_by_category",
                "mart_revenue_by_region", "mart_sales_daily"]:
        cur.execute(f"SELECT COUNT(*), MIN(year), MAX(year) FROM {tbl}")
        n, mn, mx = cur.fetchone()
        print(f"  {tbl:<30} {n:>5} rows | years {mn} – {mx}")
    con.close()

    print()
    print("All done. Data now covers 2022–2026 Apr.")


if __name__ == "__main__":
    main()
