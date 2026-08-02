-- OPTION B — wide curated store, long exposed as a view.
-- Apply 00_common.sql first. Target: PostgreSQL 16 on a GCP e2-micro VM.
-- STATUS: not yet executed; parse-checked only.
--
-- Written to be genuinely usable, not a strawman. The case for it is real:
-- all 39 history metrics share one identical timestamp set (D3), so rows are
-- dense rather than sparse, and a feature matrix is a plain SELECT.

CREATE TYPE observation_source AS ENUM ('observed', 'resampled', 'backfilled');

CREATE TABLE observation_wide (
    station_id text        NOT NULL,
    ts_utc     timestamptz NOT NULL,

    -- outdoor
    outdoor_temperature      double precision,
    outdoor_feels_like       double precision,
    outdoor_app_temp         double precision,
    outdoor_dew_point        double precision,
    outdoor_vpd              double precision,
    outdoor_humidity         double precision,
    -- indoor
    indoor_temperature       double precision,
    indoor_humidity          double precision,
    indoor_dew_point         double precision,
    indoor_feels_like        double precision,
    indoor_app_tempin        double precision,
    -- solar
    solar                    double precision,
    uvi                      double precision,
    -- rainfall (piezo only; this station has no tipping bucket)
    rainfall_piezo_rain_rate double precision,
    rainfall_piezo_event     double precision,
    rainfall_piezo_1_hour    double precision,
    rainfall_piezo_daily     double precision,
    rainfall_piezo_weekly    double precision,
    rainfall_piezo_monthly   double precision,
    rainfall_piezo_yearly    double precision,
    -- wind
    wind_speed               double precision,
    wind_gust                double precision,
    wind_direction           double precision,
    -- pressure
    pressure_relative        double precision,
    pressure_absolute        double precision,
    -- extra T/RH channels (station supports 8; 3 attached)
    temp_and_humidity_ch1_temperature double precision,
    temp_and_humidity_ch1_humidity    double precision,
    temp_and_humidity_ch2_temperature double precision,
    temp_and_humidity_ch2_humidity    double precision,
    temp_and_humidity_ch3_temperature double precision,
    temp_and_humidity_ch3_humidity    double precision,
    -- soil (station supports 16; 2 attached)
    soil_ch1_soilmoisture    double precision,
    soil_ch1_ad              integer,
    soil_ch2_soilmoisture    double precision,
    soil_ch2_ad              integer,
    -- battery: volts
    battery_haptic_array_battery   double precision,
    battery_haptic_array_capacitor double precision,
    battery_soilmoisture_sensor_ch1 double precision,
    battery_soilmoisture_sensor_ch2 double precision,
    -- battery: unitless status codes, real-time only (D3 asymmetry)
    battery_temp_humidity_sensor_ch1 text,
    battery_temp_humidity_sensor_ch2 text,
    battery_temp_humidity_sensor_ch3 text,

    source         observation_source NOT NULL DEFAULT 'observed',
    first_seen_run uuid  NOT NULL REFERENCES run_log (run_id),
    last_seen_run  uuid  NOT NULL REFERENCES run_log (run_id),
    updated_at     timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (station_id, ts_utc)
);

CREATE INDEX observation_wide_time ON observation_wide (ts_utc DESC);

-- ---------------------------------------------------------------------------
-- Units cannot live in the row.
--
-- §10 requires recording the unit each value arrived in, and units are
-- per-metric, not per-row: outdoor_vpd is inHg while outdoor_temperature is
-- ºF. Three ways to model that, none good:
--   (a) 42 parallel *_unit columns  -> 84 columns, mostly constant
--   (b) one unit set per row        -> loses per-metric fidelity
--   (c) a side table keyed by metric -> reintroduces the long table
-- (c) is chosen here as the least bad, which is worth noticing: the wide
-- design needs a metric-keyed table anyway.
-- ---------------------------------------------------------------------------

CREATE TABLE observation_wide_units (
    column_name text PRIMARY KEY,
    metric      text NOT NULL REFERENCES metric_catalog (metric),
    unit        text NOT NULL,
    valid_from  timestamptz NOT NULL DEFAULT now(),
    valid_to    timestamptz
);

-- ---------------------------------------------------------------------------
-- Raw text is not preserved.
--
-- Option A keeps value_text (exact bytes) beside value_num. Doing that here
-- would mean 42 more text columns. The raw JSON in raw_payload remains the
-- fallback, so nothing is lost permanently -- but recovering an unparseable
-- value means re-reading raw_payload rather than reading the curated row, and
-- a value that fails to parse can only be represented as NULL, which is
-- indistinguishable from "sensor reported nothing".
-- ---------------------------------------------------------------------------

-- ---------------------------------------------------------------------------
-- Change detection: no single-statement equivalent.
--
-- Option A's upsert reports insert/update/unchanged from one RETURNING clause.
-- Here every changed column must be compared explicitly, and change_log needs
-- one row per changed field -- so the column list is written out 42 times in
-- the WHERE, and again in whatever emits change_log rows. Abridged:
-- ---------------------------------------------------------------------------

-- INSERT INTO observation_wide AS o (station_id, ts_utc, outdoor_temperature, ...)
-- VALUES (...)
-- ON CONFLICT (station_id, ts_utc) DO UPDATE
--     SET outdoor_temperature = EXCLUDED.outdoor_temperature,
--         ...                                        -- x42
--         last_seen_run = EXCLUDED.last_seen_run,
--         updated_at = now()
--     WHERE o.outdoor_temperature IS DISTINCT FROM EXCLUDED.outdoor_temperature
--        OR o.outdoor_humidity    IS DISTINCT FROM EXCLUDED.outdoor_humidity
--        OR ...                                      -- x42, and every one must
--                                                    -- be kept in sync forever
-- RETURNING (xmax = 0) AS was_insert, o.*;
--
-- "Which field changed" then has to be recovered by diffing the returned row
-- against the input in application code -- work the long form gets for free.

-- ---------------------------------------------------------------------------
-- Long view, for change_log joins and per-metric queries.
-- ---------------------------------------------------------------------------

CREATE VIEW observation_long AS
SELECT station_id, ts_utc, 'outdoor.temperature' AS metric,
       outdoor_temperature AS value_num, source
FROM observation_wide
UNION ALL
SELECT station_id, ts_utc, 'outdoor.humidity', outdoor_humidity, source
FROM observation_wide
UNION ALL
SELECT station_id, ts_utc, 'wind.wind_direction', wind_direction, source
FROM observation_wide;
-- ... one UNION ALL branch per metric, x42. Unlike Option A's pivot, this
-- unpivot rescans the table once per branch unless materialised.

-- ---------------------------------------------------------------------------
-- Adding a sensor: a migration, on a table holding training data.
-- ---------------------------------------------------------------------------

-- ALTER TABLE observation_wide
--     ADD COLUMN soil_ch3_soilmoisture double precision,
--     ADD COLUMN soil_ch3_ad           integer;
-- -- plus: update the upsert statement, the WHERE clause, the change-detection
-- -- diff, observation_long, and every downstream view. Rows before the ALTER
-- -- carry NULL, which is indistinguishable from "sensor present but silent".
