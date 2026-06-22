-- Fails if any category in the mart is not one of the five known CPG categories.
-- Guards against schema drift or bad joins introducing unknown category values.
SELECT DISTINCT category
FROM {{ ref('mart_forecast_inputs') }}
WHERE category NOT IN (
    'Beverages',
    'Snacks',
    'Dairy',
    'Household',
    'Personal Care'
)
