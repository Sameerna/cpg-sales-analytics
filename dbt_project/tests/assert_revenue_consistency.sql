-- Fails if total revenue in mart_revenue_by_category diverges from
-- mart_forecast_inputs by more than 1%. The two marts aggregate from the
-- same source; a large gap indicates a broken join or filter.
WITH cat_total AS (
    SELECT SUM(total_revenue) AS rev
    FROM {{ ref('mart_revenue_by_category') }}
),
forecast_total AS (
    SELECT SUM(monthly_revenue) AS rev
    FROM {{ ref('mart_forecast_inputs') }}
)
SELECT
    cat_total.rev        AS category_mart_rev,
    forecast_total.rev   AS forecast_mart_rev,
    ABS(cat_total.rev - forecast_total.rev) / NULLIF(cat_total.rev, 0) AS pct_diff
FROM cat_total, forecast_total
WHERE ABS(cat_total.rev - forecast_total.rev) / NULLIF(cat_total.rev, 0) > 0.01
