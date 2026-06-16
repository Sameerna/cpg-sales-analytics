SELECT
    p.category,
    t.year,
    t.month,
    COUNT(t.transaction_id)     AS transaction_count,
    SUM(t.quantity)             AS total_quantity,
    ROUND(SUM(t.revenue), 2)    AS total_revenue,
    ROUND(AVG(t.unit_price), 2) AS avg_unit_price
FROM {{ ref('stg_transactions') }} t
LEFT JOIN {{ ref('stg_products') }} p ON t.sku_id = p.sku_id
WHERE p.category IS NOT NULL
GROUP BY p.category, t.year, t.month
