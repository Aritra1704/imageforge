-- Optional helper queries for local verification.

SELECT 'image_requests' AS table_name, COUNT(*) AS row_count
FROM imageforge.image_requests
UNION ALL
SELECT 'image_provider_runs' AS table_name, COUNT(*) AS row_count
FROM imageforge.image_provider_runs
UNION ALL
SELECT 'image_candidates' AS table_name, COUNT(*) AS row_count
FROM imageforge.image_candidates
UNION ALL
SELECT 'image_feedback' AS table_name, COUNT(*) AS row_count
FROM imageforge.image_feedback
UNION ALL
SELECT 'image_prompt_history' AS table_name, COUNT(*) AS row_count
FROM imageforge.image_prompt_history;
