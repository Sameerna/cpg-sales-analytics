-- Fails if any month/category/region row has negative or zero revenue.
-- Every mart row must represent real sales activity.
SELECT *
FROM {{ ref('mart_forecast_inputs') }}
WHERE monthly_revenue <= 0
