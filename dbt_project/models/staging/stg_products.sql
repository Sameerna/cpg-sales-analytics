SELECT
    sku_id,
    category,
    subcategory,
    brand,
    package_size,
    CAST(list_price AS REAL) AS list_price,
    launch_date,
    is_new_launch
FROM {{ source('main', 'clean_products') }}
