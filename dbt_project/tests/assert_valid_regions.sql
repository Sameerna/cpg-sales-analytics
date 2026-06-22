-- Fails if any region value is not one of the four known regions.
-- Catches store-to-region mapping failures in stg_stores.
SELECT DISTINCT region
FROM {{ ref('mart_forecast_inputs') }}
WHERE region NOT IN ('North', 'South', 'East', 'West')
