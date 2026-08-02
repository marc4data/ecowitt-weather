-- OPTION B — wide curated store, long exposed as a view. BigQuery.
-- Apply 00_common.sql first, and run assertions.sql on every load.
-- STATUS: not yet executed; parse-checked as BigQuery only.
--
-- Written to be genuinely usable, not a strawman — and on BigQuery its case is
-- considerably stronger than it was on Postgres:
--   * columnar storage means unused columns cost nothing to store or scan
--   * ALTER TABLE ADD COLUMN is a free metadata operation, no table rewrite
--   * 105k rows/year instead of 4.4M means MERGE touches 42x fewer rows
-- The first two gut the two biggest arguments that favoured long on Postgres.

CREATE TABLE IF NOT EXISTS ecowitt.observation_wide (
    station_id STRING    NOT NULL,
    ts_utc     TIMESTAMP NOT NULL,

    -- outdoor
    outdoor_temperature      FLOAT64,
    outdoor_feels_like       FLOAT64,
    outdoor_app_temp         FLOAT64,
    outdoor_dew_point        FLOAT64,
    outdoor_vpd              FLOAT64,
    outdoor_humidity         FLOAT64,
    -- indoor
    indoor_temperature       FLOAT64,
    indoor_humidity          FLOAT64,
    indoor_dew_point         FLOAT64,
    indoor_feels_like        FLOAT64,
    indoor_app_tempin        FLOAT64,
    -- solar
    solar                    FLOAT64,
    uvi                      FLOAT64,
    -- rainfall (piezo only; this station has no tipping bucket)
    rainfall_piezo_rain_rate FLOAT64,
    rainfall_piezo_event     FLOAT64,
    rainfall_piezo_1_hour    FLOAT64,
    rainfall_piezo_daily     FLOAT64,
    rainfall_piezo_weekly    FLOAT64,
    rainfall_piezo_monthly   FLOAT64,
    rainfall_piezo_yearly    FLOAT64,
    -- wind
    wind_speed               FLOAT64,
    wind_gust                FLOAT64,
    wind_direction           FLOAT64,
    -- pressure
    pressure_relative        FLOAT64,
    pressure_absolute        FLOAT64,
    -- extra T/RH channels (station supports 8; 3 attached)
    temp_and_humidity_ch1_temperature FLOAT64,
    temp_and_humidity_ch1_humidity    FLOAT64,
    temp_and_humidity_ch2_temperature FLOAT64,
    temp_and_humidity_ch2_humidity    FLOAT64,
    temp_and_humidity_ch3_temperature FLOAT64,
    temp_and_humidity_ch3_humidity    FLOAT64,
    -- soil (station supports 16; 2 attached)
    soil_ch1_soilmoisture    FLOAT64,
    soil_ch1_ad              INT64,
    soil_ch2_soilmoisture    FLOAT64,
    soil_ch2_ad              INT64,
    -- battery: volts
    battery_haptic_array_battery    FLOAT64,
    battery_haptic_array_capacitor  FLOAT64,
    battery_soilmoisture_sensor_ch1 FLOAT64,
    battery_soilmoisture_sensor_ch2 FLOAT64,
    -- battery: unitless status codes, real-time only (D3 endpoint asymmetry)
    battery_temp_humidity_sensor_ch1 STRING,
    battery_temp_humidity_sensor_ch2 STRING,
    battery_temp_humidity_sensor_ch3 STRING,

    source         STRING    NOT NULL,
    first_seen_run STRING    NOT NULL,
    last_seen_run  STRING    NOT NULL,
    updated_at     TIMESTAMP NOT NULL,

    PRIMARY KEY (station_id, ts_utc) NOT ENFORCED
)
PARTITION BY DATE(ts_utc)
CLUSTER BY station_id
OPTIONS (
    description = 'Curated observations, one row per (station, timestamp).',
    require_partition_filter = TRUE
);

-- ---------------------------------------------------------------------------
-- Units still cannot live in the row.
--
-- §10 requires recording the unit each value arrived in, and units are
-- per-metric: outdoor_vpd is inHg while outdoor_temperature is ºF. Options:
--   (a) 42 parallel *_unit columns  -> 84 columns, nearly all constant
--   (b) one unit set per row        -> loses per-metric fidelity
--   (c) a metric-keyed side table   -> reintroduces a long table
-- (c) is chosen, which is worth noticing: the wide design needs a
-- metric-keyed table anyway. On BigQuery (a) is cheaper than it was on
-- Postgres — columnar storage barely notices 42 near-constant columns — but it
-- is still 84 columns to keep in sync by hand.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ecowitt.observation_wide_units (
    column_name STRING    NOT NULL,
    metric      STRING    NOT NULL,
    unit        STRING    NOT NULL,
    valid_from  TIMESTAMP NOT NULL,
    valid_to    TIMESTAMP,

    PRIMARY KEY (column_name, valid_from) NOT ENFORCED
);

-- ---------------------------------------------------------------------------
-- Raw text is not preserved.
--
-- Option A keeps value_text (exact bytes) beside value_num. Doing that here
-- means 42 more STRING columns. Without them, a value that fails to parse can
-- only be NULL — indistinguishable from "sensor reported nothing", which is
-- precisely the ambiguity §10's no-unconditional-casts rule exists to prevent.
-- The raw JSON in raw_payload remains the fallback, so nothing is lost
-- permanently, but recovery means re-reading raw payloads rather than reading
-- the curated row.
-- ---------------------------------------------------------------------------

-- ---------------------------------------------------------------------------
-- Change detection: the column list, written out twice, forever.
-- ---------------------------------------------------------------------------

-- MERGE ecowitt.observation_wide AS t
-- USING ecowitt._staging_wide AS s
--   ON t.station_id = s.station_id AND t.ts_utc = s.ts_utc
--  AND DATE(t.ts_utc) BETWEEN @window_start_date AND @window_end_date
-- WHEN MATCHED AND (
--        t.outdoor_temperature IS DISTINCT FROM s.outdoor_temperature
--     OR t.outdoor_humidity    IS DISTINCT FROM s.outdoor_humidity
--     OR ...                                     -- x42, hand-maintained
-- ) THEN UPDATE SET
--     outdoor_temperature = s.outdoor_temperature,
--     ...                                        -- x42, hand-maintained
--     updated_at = CURRENT_TIMESTAMP()
-- WHEN NOT MATCHED THEN INSERT ROW;
--
-- §7's change_log is field-level, so emitting it requires knowing WHICH column
-- differed. That means either 42 UNION ALL branches comparing one column each,
-- or diffing the returned row in application code. Option A gets this from the
-- row identity itself.

-- ---------------------------------------------------------------------------
-- Long view, for change_log joins and per-metric queries.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW ecowitt.observation_long AS
SELECT station_id, ts_utc, metric, value_num, source
FROM ecowitt.observation_wide,
UNNEST([
    STRUCT('outdoor.temperature' AS metric, outdoor_temperature AS value_num),
    STRUCT('outdoor.humidity',              outdoor_humidity),
    STRUCT('outdoor.dew_point',             outdoor_dew_point),
    STRUCT('wind.wind_speed',               wind_speed),
    STRUCT('wind.wind_gust',                wind_gust),
    STRUCT('wind.wind_direction',           wind_direction),
    STRUCT('pressure.absolute',             pressure_absolute),
    STRUCT('solar_and_uvi.solar',           solar)
    -- ... one STRUCT per metric, x42, hand-maintained
]);
-- UNNEST of a struct array avoids the repeated table scan a UNION ALL unpivot
-- would cause — a genuine BigQuery advantage over the Postgres draft.

-- ---------------------------------------------------------------------------
-- Adding a sensor: cheap on BigQuery, unlike Postgres.
-- ---------------------------------------------------------------------------

-- ALTER TABLE ecowitt.observation_wide
--     ADD COLUMN soil_ch3_soilmoisture FLOAT64,
--     ADD COLUMN soil_ch3_ad           INT64;
--
-- Metadata-only: instant, no rewrite, no downtime, no backfill. But the
-- surrounding code still changes -- the MERGE SET list, the MERGE WHERE list,
-- the change-detection diff, observation_long, and every downstream view. And
-- rows written before the ALTER carry NULL, indistinguishable from "sensor
-- present but silent".
