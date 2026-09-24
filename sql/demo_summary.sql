-- The caller registers only the explicitly selected April development rows as demo.
-- No file access or test targets are required by this reusable aggregation.
SELECT borough, COUNT(*) AS zone_hours,
       SUM(demand)::BIGINT AS recorded_pickups,
       AVG(ABS(demand - hist_gradient_boosting)) AS temporal_mae,
       AVG(ABS(demand - borough_context)) AS borough_context_mae,
       AVG(ABS(demand - previous_week_168h)) AS weekly_mae
FROM demo
GROUP BY borough
ORDER BY recorded_pickups DESC;
