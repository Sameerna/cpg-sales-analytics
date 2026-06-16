SELECT
    transaction_id,
    DATE(timestamp)                                                     AS sale_date,
    STRFTIME('%Y', timestamp)                                           AS year,
    STRFTIME('%m', timestamp)                                           AS month,
    sku_id,
    store_id,
    CAST(quantity   AS INTEGER)                                         AS quantity,
    CAST(unit_price AS REAL)                                            AS unit_price,
    ROUND(CAST(quantity AS REAL) * CAST(unit_price AS REAL), 2)        AS revenue,
    channel,
    customer_id
FROM {{ source('main', 'clean_transactions') }}
