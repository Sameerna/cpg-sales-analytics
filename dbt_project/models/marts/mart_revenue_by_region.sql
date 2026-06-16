SELECT
    s.region,
    t.year,
    t.month,
    COUNT(t.transaction_id)     AS transaction_count,
    SUM(t.quantity)             AS total_quantity,
    ROUND(SUM(t.revenue), 2)    AS total_revenue
FROM {{ ref('stg_transactions') }} t
LEFT JOIN {{ ref('stg_stores') }} s ON t.store_id = s.store_id
WHERE s.region IS NOT NULL
GROUP BY s.region, t.year, t.month
