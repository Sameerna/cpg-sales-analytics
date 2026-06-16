SELECT
    promo_id,
    sku_id,
    category,
    start_date,
    end_date,
    CAST(discount_pct AS REAL) AS discount_pct,
    channel
FROM {{ source('main', 'clean_promotions') }}
