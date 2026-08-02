-- OPTION A — long/tall curated store, wide exposed as a view. BigQuery.
-- Apply 00_common.sql first, and run assertions.sql on every load.
-- STATUS: not yet executed; parse-checked as BigQuery only.

CREATE TABLE IF NOT EXISTS ecowitt.observation (
    station_id     STRING    NOT NULL,
    ts_utc         TIMESTAMP NOT NULL,
    metric         STRING    NOT NULL,

    -- Two columns on purpose. value_text is the exact bytes the API returned;
    -- value_num is the parsed form, NULL when it does not parse. §10 forbids
    -- unconditional casts, and an unparseable value must be a recorded fact
    -- rather than an ingest crash — or, worse, a NULL indistinguishable from
    -- "the sensor said nothing".
    value_text     STRING    NOT NULL,
    value_num      FLOAT64,

    -- Exact bytes, never normalised. D4: the API returns ºF (U+00BA) and
    -- ℃ (U+2103) from the same parameter; a °/º cleanup rewrites history.
    unit           STRING    NOT NULL,

    source         STRING    NOT NULL,   -- observed|resampled|backfilled
    first_seen_run STRING    NOT NULL,
    last_seen_run  STRING    NOT NULL,
    updated_at     TIMESTAMP NOT NULL,

    -- NOT ENFORCED: metadata for the optimizer, not a guarantee. Idempotency
    -- comes from the MERGE below, and is verified by assertions.sql §6.
    PRIMARY KEY (station_id, ts_utc, metric) NOT ENFORCED,
    FOREIGN KEY (metric) REFERENCES ecowitt.metric_catalog (metric) NOT ENFORCED
)
PARTITION BY DATE(ts_utc)
-- Clustering on metric is what keeps the long form cheap: a query for one
-- metric prunes blocks instead of scanning every metric for that day.
CLUSTER BY metric, station_id
OPTIONS (
    description = 'Curated observations, one row per (station, timestamp, metric).',
    require_partition_filter = TRUE
);

-- ---------------------------------------------------------------------------
-- Idempotent load with change detection (§7)
--
-- Batch-load the pull into a staging table, then MERGE. Batch loads are free
-- and, unlike the legacy streaming API, leave no streaming buffer to block the
-- MERGE — which matters because §10 says backfill and incremental runs
-- overlap by design.
--
-- The `AND (... IS DISTINCT FROM ...)` on WHEN MATCHED is what makes this a
-- change-detecting load rather than the blind upsert §7 forbids: matched rows
-- that are identical fall through untouched and are counted as unchanged.
-- ---------------------------------------------------------------------------

-- MERGE ecowitt.observation AS t
-- USING ecowitt._staging_observation AS s
--   ON  t.station_id = s.station_id
--   AND t.ts_utc     = s.ts_utc
--   AND t.metric     = s.metric
--   AND DATE(t.ts_utc) BETWEEN @window_start_date AND @window_end_date
-- WHEN MATCHED AND (t.value_text IS DISTINCT FROM s.value_text
--                OR t.unit       IS DISTINCT FROM s.unit) THEN UPDATE SET
--     value_text = s.value_text,
--     value_num  = s.value_num,
--     unit       = s.unit,
--     last_seen_run = s.last_seen_run,
--     updated_at = CURRENT_TIMESTAMP()
-- WHEN NOT MATCHED THEN INSERT ROW;
--
-- The DATE(...) BETWEEN predicate is not cosmetic: without it the MERGE scans
-- every partition ever written, which is both slow and the one way this design
-- could actually cost money.
--
-- BigQuery's MERGE does not report which rows were inserted vs updated vs
-- untouched. §7 requires those counts, so capture them explicitly before the
-- MERGE -- and emit change_log rows from the same comparison:
--
-- INSERT INTO ecowitt.change_log (...)
-- SELECT GENERATE_UUID(), s.station_id, s.ts_utc, s.metric,
--        t.value_text, s.value_text, t.unit, s.unit,
--        @run_id, CURRENT_TIMESTAMP(), 'value changed on re-fetch'
-- FROM ecowitt._staging_observation s
-- JOIN ecowitt.observation t USING (station_id, ts_utc, metric)
-- WHERE t.value_text IS DISTINCT FROM s.value_text
--    OR t.unit       IS DISTINCT FROM s.unit;

-- ---------------------------------------------------------------------------
-- Wide view (§1: derived views are in scope)
--
-- Cheap and unambiguous because all 39 history metrics share one identical
-- timestamp set (D3) — the pivot has no ragged edges. Abridged here; generate
-- the full view from metric_catalog so a new sensor needs no edit.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW ecowitt.observation_wide AS
SELECT
    station_id,
    ts_utc,
    MAX(IF(metric = 'outdoor.temperature',      value_num, NULL)) AS outdoor_temperature_f,
    MAX(IF(metric = 'outdoor.humidity',         value_num, NULL)) AS outdoor_humidity_pct,
    MAX(IF(metric = 'outdoor.dew_point',        value_num, NULL)) AS outdoor_dew_point_f,
    MAX(IF(metric = 'pressure.absolute',        value_num, NULL)) AS pressure_absolute_inhg,
    MAX(IF(metric = 'wind.wind_speed',          value_num, NULL)) AS wind_speed_mph,
    MAX(IF(metric = 'wind.wind_gust',           value_num, NULL)) AS wind_gust_mph,
    MAX(IF(metric = 'wind.wind_direction',      value_num, NULL)) AS wind_direction_deg,
    MAX(IF(metric = 'rainfall_piezo.rain_rate', value_num, NULL)) AS rain_rate_in_hr,
    MAX(IF(metric = 'solar_and_uvi.solar',      value_num, NULL)) AS solar_wm2,
    MAX(IF(metric = 'soil_ch1.soilmoisture',    value_num, NULL)) AS soil_ch1_pct,
    MAX(IF(metric = 'soil_ch2.soilmoisture',    value_num, NULL)) AS soil_ch2_pct,
    -- Never let synthesized values into a feature matrix unnoticed (§9).
    LOGICAL_OR(source = 'resampled')                              AS has_synthesized
FROM ecowitt.observation
GROUP BY station_id, ts_utc;

-- Units decided 2026-08-02: imperial canonical, metric derived on read.
CREATE OR REPLACE VIEW ecowitt.observation_wide_metric AS
SELECT
    station_id,
    ts_utc,
    (outdoor_temperature_f - 32) * 5 / 9 AS outdoor_temperature_c,
    (outdoor_dew_point_f   - 32) * 5 / 9 AS outdoor_dew_point_c,
    pressure_absolute_inhg * 33.8639     AS pressure_absolute_hpa,
    wind_speed_mph * 0.44704             AS wind_speed_ms,
    wind_gust_mph  * 0.44704             AS wind_gust_ms,
    rain_rate_in_hr * 25.4               AS rain_rate_mm_hr,
    outdoor_humidity_pct,
    wind_direction_deg,
    solar_wm2,
    has_synthesized
FROM ecowitt.observation_wide;

-- ---------------------------------------------------------------------------
-- Point-in-time reconstruction (§8) — a filter, not a pivot.
-- "What did the record for timestamp T look like as of date D?"
-- ---------------------------------------------------------------------------

-- SELECT o.station_id, o.ts_utc, o.metric,
--        COALESCE(
--            ARRAY_AGG(c.old_value ORDER BY c.changed_at ASC LIMIT 1)[SAFE_OFFSET(0)],
--            o.value_text
--        ) AS value_as_of
-- FROM ecowitt.observation o
-- LEFT JOIN ecowitt.change_log c
--        ON c.station_id = o.station_id
--       AND c.ts_utc     = o.ts_utc
--       AND c.metric     = o.metric
--       AND c.changed_at > @as_of
-- WHERE DATE(o.ts_utc) = @target_date
-- GROUP BY o.station_id, o.ts_utc, o.metric, o.value_text;

-- ---------------------------------------------------------------------------
-- Adding a sensor: two INSERTs into metric_catalog. No DDL at all.
-- ---------------------------------------------------------------------------

-- INSERT INTO ecowitt.metric_catalog VALUES
--   ('soil_ch3.soilmoisture', 'instantaneous', '%', 'mean',  TRUE,  NULL),
--   ('soil_ch3.ad',           'opaque',        '',  'carry', FALSE, 'raw ADC');
