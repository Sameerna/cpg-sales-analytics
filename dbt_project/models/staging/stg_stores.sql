SELECT
    store_id,
    region,
    store_type,
    store_tier,
    CAST(store_size_sqm           AS INTEGER) AS store_size_sqm,
    CAST(weekly_footfall_estimate AS INTEGER) AS weekly_footfall_estimate,
    has_online_delivery,
    demographic_segment
FROM {{ source('main', 'clean_stores') }}
