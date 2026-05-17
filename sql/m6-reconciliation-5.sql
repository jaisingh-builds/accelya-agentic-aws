-- ╔═══════════════════════════════════════════════════════════════════════╗
-- ║  Day 6 Lab 2 — Five reconciliation queries                            ║
-- ║                                                                       ║
-- ║  Run each query against BOTH tables to prove the cost reduction:      ║
-- ║    1. accelya_validated_<learner>.validated_settlement_json (JSON)    ║
-- ║    2. accelya_curated_<learner>.settlement (Parquet)                  ║
-- ║                                                                       ║
-- ║  Use the per-learner workgroup `accelya_<learner>` which enforces     ║
-- ║  BytesScannedCutoffPerQuery=104857600 (100 MB).                       ║
-- ║                                                                       ║
-- ║  REPLACE <learner> with your actual name BEFORE running.              ║
-- ║                                                                       ║
-- ║  Every query MUST include a WHERE on at least one partition column    ║
-- ║  (ingest_date or source_system).                                      ║
-- ╚═══════════════════════════════════════════════════════════════════════╝


-- ╭───────────────────────────────────────────────────────────────────────╮
-- │ Q1 · Settlement-by-airline                                            │
-- │   For one ingest_date + one source_system, total fares per airline.   │
-- │   Expected scan (Parquet): ~1 MB. (JSON: 30-100 MB.)                  │
-- ╰───────────────────────────────────────────────────────────────────────╯

SELECT
    airline_code,
    COUNT(*)                                       AS settlement_count,
    SUM(CAST(fare_amount AS DECIMAL(12,2)))        AS total_fare,
    AVG(CAST(fare_amount AS DECIMAL(12,2)))        AS avg_fare,
    MIN(CAST(fare_amount AS DECIMAL(12,2)))        AS min_fare,
    MAX(CAST(fare_amount AS DECIMAL(12,2)))        AS max_fare
FROM accelya_curated_<learner>.settlement
WHERE ingest_date  = '2026-05-09'
  AND source_system = 'BSP'
GROUP BY airline_code
ORDER BY total_fare DESC
LIMIT 25;


-- ╭───────────────────────────────────────────────────────────────────────╮
-- │ Q2 · Missing ticket numbers (data quality probe)                      │
-- │   Find rows where ticket_number is NULL or empty.                     │
-- │   Should be very low on real data; spikes indicate upstream issues.   │
-- ╰───────────────────────────────────────────────────────────────────────╯

SELECT
    ingest_date,
    source_system,
    airline_code,
    COUNT(*) AS rows_missing_ticket
FROM accelya_curated_<learner>.settlement
WHERE ingest_date BETWEEN '2026-05-09' AND '2026-05-10'
  AND (ticket_number IS NULL OR ticket_number = '')
GROUP BY ingest_date, source_system, airline_code
ORDER BY rows_missing_ticket DESC
LIMIT 50;


-- ╭───────────────────────────────────────────────────────────────────────╮
-- │ Q3 · Refund-rate by OD-pair                                           │
-- │   Refund rate = refunded settlements / total settlements per route.   │
-- │   High refund rates flag overbookings or route disruptions.           │
-- ╰───────────────────────────────────────────────────────────────────────╯

SELECT
    od_pair,
    source_system,
    COUNT(*)                                                       AS total_settlements,
    SUM(CASE WHEN refund_status IS NOT NULL THEN 1 ELSE 0 END)     AS refunded,
    ROUND(
        CAST(SUM(CASE WHEN refund_status IS NOT NULL THEN 1 ELSE 0 END) AS DOUBLE)
        / CAST(COUNT(*) AS DOUBLE),
        4
    )                                                              AS refund_rate
FROM accelya_curated_<learner>.settlement
WHERE ingest_date  = '2026-05-09'
  AND source_system IN ('BSP', 'ARC', 'ATPCO')
GROUP BY od_pair, source_system
HAVING COUNT(*) >= 5
ORDER BY refund_rate DESC, total_settlements DESC
LIMIT 25;


-- ╭───────────────────────────────────────────────────────────────────────╮
-- │ Q4 · Top-OD-pairs by total fare                                       │
-- │   Highest-revenue routes for one week of ingest_dates.                │
-- ╰───────────────────────────────────────────────────────────────────────╯

SELECT
    od_pair,
    COUNT(*)                                       AS settlement_count,
    SUM(CAST(fare_amount AS DECIMAL(12,2)))        AS total_fare,
    AVG(CAST(fare_amount AS DECIMAL(12,2)))        AS avg_fare
FROM accelya_curated_<learner>.settlement
WHERE ingest_date BETWEEN '2026-05-04' AND '2026-05-10'
  AND source_system = 'BSP'
GROUP BY od_pair
ORDER BY total_fare DESC
LIMIT 20;


-- ╭───────────────────────────────────────────────────────────────────────╮
-- │ Q5 · Fare anomalies vs 7-day median                                   │
-- │   Settlements whose fare_amount is >3x the 7-day rolling median       │
-- │   for the same OD-pair.                                               │
-- │                                                                       │
-- │   Window functions on Parquet are dramatically cheaper than JSON      │
-- │   because Athena only reads (fare_amount, od_pair, issue_date)        │
-- │   column chunks — not the whole row.                                  │
-- ╰───────────────────────────────────────────────────────────────────────╯

WITH base AS (
    SELECT
        ingest_date,
        source_system,
        settlement_id,
        od_pair,
        airline_code,
        CAST(fare_amount AS DECIMAL(12,2)) AS fare_amount,
        issue_date
    FROM accelya_curated_<learner>.settlement
    WHERE ingest_date BETWEEN '2026-05-04' AND '2026-05-10'
      AND source_system = 'BSP'
),
medians AS (
    SELECT
        od_pair,
        APPROX_PERCENTILE(fare_amount, 0.5) AS median_fare
    FROM base
    GROUP BY od_pair
)
SELECT
    b.ingest_date,
    b.settlement_id,
    b.od_pair,
    b.airline_code,
    b.fare_amount,
    m.median_fare,
    ROUND(b.fare_amount / NULLIF(m.median_fare, 0), 2) AS ratio_to_median
FROM base b
JOIN medians m USING (od_pair)
WHERE b.fare_amount > 3 * m.median_fare
ORDER BY ratio_to_median DESC
LIMIT 25;


-- ╔═══════════════════════════════════════════════════════════════════════╗
-- ║  JSON-vs-Parquet A/B template                                         ║
-- ║                                                                       ║
-- ║  Run Q1 against BOTH tables. Capture DataScannedInBytes from each     ║
-- ║  via `aws athena get-query-execution --query-execution-id <id>`       ║
-- ║  --query 'QueryExecution.Statistics.DataScannedInBytes'               ║
-- ║                                                                       ║
-- ║  Then compute the ratio:                                              ║
-- ║      ratio = json_scanned / parquet_scanned                           ║
-- ║                                                                       ║
-- ║  Target: >=10x. Often >=100x at lab scale.                            ║
-- ║                                                                       ║
-- ║  Document in /reviews/m6-query-cost-evidence.md                       ║
-- ╚═══════════════════════════════════════════════════════════════════════╝

-- Q1 — JSON version (same SQL, different table):
-- SELECT
--     airline_code,
--     COUNT(*)                                       AS settlement_count,
--     SUM(CAST(fare_amount AS DECIMAL(12,2)))        AS total_fare,
--     AVG(CAST(fare_amount AS DECIMAL(12,2)))        AS avg_fare,
--     MIN(CAST(fare_amount AS DECIMAL(12,2)))        AS min_fare,
--     MAX(CAST(fare_amount AS DECIMAL(12,2)))        AS max_fare
-- FROM accelya_validated_<learner>.validated_settlement_json
-- WHERE ingest_date  = '2026-05-09'
--   AND source_system = 'BSP'
-- GROUP BY airline_code
-- ORDER BY total_fare DESC
-- LIMIT 25;
