-- Fails if mart_forecast_inputs has fewer than 240 rows.
-- 5 categories × 4 regions × 12 months × 3 complete years = 720 expected minimum.
-- 240 is a conservative floor to catch catastrophic join failures.
SELECT COUNT(*) AS row_count
FROM {{ ref('mart_forecast_inputs') }}
HAVING COUNT(*) < 240
