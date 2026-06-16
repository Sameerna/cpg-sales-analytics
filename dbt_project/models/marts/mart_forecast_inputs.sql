-- Monthly feature table for Ridge regression.
-- One row per (year, month, category, region).
WITH monthly_sales AS (
    SELECT
        year,
        month,
        category,
        region,
        SUM(total_revenue)      AS monthly_revenue,
        SUM(total_quantity)     AS monthly_quantity,
        SUM(transaction_count)  AS monthly_transactions,
        AVG(avg_unit_price)     AS avg_unit_price
    FROM {{ ref('mart_sales_daily') }}
    GROUP BY year, month, category, region
),

promo_agg AS (
    SELECT
        LOWER(category)              AS category,
        STRFTIME('%Y', start_date)   AS year,
        STRFTIME('%m', start_date)   AS month,
        COUNT(promo_id)              AS active_promos,
        ROUND(AVG(discount_pct), 2)  AS avg_discount_pct
    FROM {{ ref('stg_promotions') }}
    GROUP BY LOWER(category), STRFTIME('%Y', start_date), STRFTIME('%m', start_date)
)

SELECT
    ms.year,
    ms.month,
    ms.category,
    ms.region,
    ROUND(ms.monthly_revenue, 2)                         AS monthly_revenue,
    ms.monthly_quantity,
    ms.monthly_transactions,
    ROUND(ms.avg_unit_price, 2)                          AS avg_unit_price,
    COALESCE(CAST(w.avg_temp_celsius AS REAL), 0.0)      AS avg_temp_celsius,
    COALESCE(CAST(w.rainfall_mm      AS REAL), 0.0)      AS rainfall_mm,
    COALESCE(CAST(mktg.spend_usd     AS REAL), 0.0)      AS marketing_spend_usd,
    COALESCE(pf.active_promos,    0)                     AS active_promos,
    COALESCE(pf.avg_discount_pct, 0.0)                   AS avg_discount_pct
FROM monthly_sales ms
LEFT JOIN {{ source('main', 'clean_weather_data') }} w
    ON  CAST(w.year AS TEXT)                       = ms.year
    AND PRINTF('%02d', CAST(w.month AS INTEGER))   = ms.month
    AND LOWER(w.region)                            = LOWER(ms.region)
LEFT JOIN {{ source('main', 'clean_marketing_spend') }} mktg
    ON  CAST(mktg.year AS TEXT)                    = ms.year
    AND PRINTF('%02d', CAST(mktg.month AS INTEGER)) = ms.month
    AND LOWER(mktg.category)                       = LOWER(ms.category)
LEFT JOIN promo_agg pf
    ON  LOWER(pf.category) = LOWER(ms.category)
    AND pf.year            = ms.year
    AND pf.month           = ms.month
