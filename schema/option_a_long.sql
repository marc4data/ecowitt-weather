-- OPTION A — long/tall curated store, wide exposed as a view.
-- Apply 00_common.sql first. Target: PostgreSQL 16 on a GCP e2-micro VM.
-- STATUS: not yet executed; parse-checked only.

CREATE TYPE observation_source AS ENUM (
    'observed',    -- came from the API as-is
    'resampled',   -- synthesized onto the grid (§9: must stay distinguishable)
    'backfilled'   -- observed, but fetched by a backfill rather than incremental
);

CREATE TABLE observation (
    station_id  text        NOT NULL,
    ts_utc      timestamptz NOT NULL,
    metric      text        NOT NULL REFERENCES metric_catalog (metric),

    -- Two columns on purpose. value_text is the exact bytes the API returned;
    -- value_num is the parsed form, NULL when it does not parse. §10 forbids
    -- unconditional casts, and a value that fails to parse must be visible as
    -- a fact rather than as an ingest crash.
    value_text  text        NOT NULL,
    value_num   double precision,

    -- Exact bytes, never normalised. D4: the API returns ºF (U+00BA) and
    -- ℃ (U+2103) from the same parameter; a °/º cleanup rewrites history.
    unit        text        NOT NULL,

    source      observation_source NOT NULL DEFAULT 'observed',
    first_seen_run uuid     NOT NULL REFERENCES run_log (run_id),
    last_seen_run  uuid     NOT NULL REFERENCES run_log (run_id),
    updated_at  timestamptz NOT NULL DEFAULT now(),

    -- Idempotency is structural, not procedural (§10).
    PRIMARY KEY (station_id, ts_utc, metric),

    -- Unit drift becomes a constraint violation, not a silent corruption.
    -- A row whose unit differs from the pinned canonical unit for that metric
    -- simply cannot be inserted.
    CONSTRAINT observation_unit_matches_catalog
        FOREIGN KEY (metric, unit)
        REFERENCES metric_catalog (metric, canonical_unit)
);

CREATE INDEX observation_metric_time ON observation (metric, ts_utc DESC);
CREATE INDEX observation_time ON observation (ts_utc DESC);
-- Finding every synthesized value must be cheap, for audit and for excluding
-- them from training data.
CREATE INDEX observation_synthesized ON observation (ts_utc)
    WHERE source = 'resampled';

-- ---------------------------------------------------------------------------
-- Idempotent load with change detection (§7)
--
-- One statement does all four jobs: insert new, update genuinely changed,
-- leave unchanged rows untouched, and report which happened. The WHERE on
-- DO UPDATE is what makes "unchanged" a countable outcome rather than a blind
-- upsert -- §7 forbids the latter explicitly.
-- ---------------------------------------------------------------------------

-- INSERT INTO observation AS o
--     (station_id, ts_utc, metric, value_text, value_num, unit,
--      source, first_seen_run, last_seen_run)
-- VALUES (:station, :ts, :metric, :text, :num, :unit, 'observed', :run, :run)
-- ON CONFLICT (station_id, ts_utc, metric) DO UPDATE
--     SET value_text = EXCLUDED.value_text,
--         value_num  = EXCLUDED.value_num,
--         unit       = EXCLUDED.unit,
--         last_seen_run = EXCLUDED.last_seen_run,
--         updated_at = now()
--     WHERE o.value_text IS DISTINCT FROM EXCLUDED.value_text
--        OR o.unit       IS DISTINCT FROM EXCLUDED.unit
-- RETURNING (xmax = 0) AS was_insert, o.value_text AS old_value;
--
-- xmax = 0 distinguishes insert from update, so run_log's inserted/updated/
-- unchanged counters come straight from the statement. Rows that conflict but
-- fail the WHERE return nothing -- those are the unchanged ones.

-- ---------------------------------------------------------------------------
-- Wide view (§1: derived views are in scope)
--
-- Cheap and unambiguous because all 39 history metrics share one identical
-- timestamp set (D3) -- the pivot has no ragged edges. Abridged here; the real
-- view is generated from metric_catalog so a new sensor needs no edit.
-- ---------------------------------------------------------------------------

CREATE VIEW observation_wide AS
SELECT
    station_id,
    ts_utc,
    MAX(value_num) FILTER (WHERE metric = 'outdoor.temperature')      AS outdoor_temperature_f,
    MAX(value_num) FILTER (WHERE metric = 'outdoor.humidity')         AS outdoor_humidity_pct,
    MAX(value_num) FILTER (WHERE metric = 'outdoor.dew_point')        AS outdoor_dew_point_f,
    MAX(value_num) FILTER (WHERE metric = 'pressure.absolute')        AS pressure_absolute_inhg,
    MAX(value_num) FILTER (WHERE metric = 'wind.wind_speed')          AS wind_speed_mph,
    MAX(value_num) FILTER (WHERE metric = 'wind.wind_gust')           AS wind_gust_mph,
    MAX(value_num) FILTER (WHERE metric = 'wind.wind_direction')      AS wind_direction_deg,
    MAX(value_num) FILTER (WHERE metric = 'rainfall_piezo.rain_rate') AS rain_rate_in_hr,
    MAX(value_num) FILTER (WHERE metric = 'solar_and_uvi.solar')      AS solar_wm2,
    MAX(value_num) FILTER (WHERE metric = 'soil_ch1.soilmoisture')    AS soil_ch1_pct,
    MAX(value_num) FILTER (WHERE metric = 'soil_ch2.soilmoisture')    AS soil_ch2_pct,
    -- Never silently mix synthesized values into a feature matrix.
    bool_or(source = 'resampled')                                     AS has_synthesized
FROM observation
GROUP BY station_id, ts_utc;

-- Metric units decided 2026-08-02: imperial canonical, metric derived on read.
CREATE VIEW observation_wide_metric AS
SELECT
    station_id,
    ts_utc,
    (outdoor_temperature_f - 32) * 5.0 / 9.0 AS outdoor_temperature_c,
    (outdoor_dew_point_f   - 32) * 5.0 / 9.0 AS outdoor_dew_point_c,
    pressure_absolute_inhg * 33.8639          AS pressure_absolute_hpa,
    wind_speed_mph * 0.44704                  AS wind_speed_ms,
    wind_gust_mph  * 0.44704                  AS wind_gust_ms,
    rain_rate_in_hr * 25.4                    AS rain_rate_mm_hr,
    outdoor_humidity_pct,
    wind_direction_deg,
    solar_wm2,
    has_synthesized
FROM observation_wide;

-- ---------------------------------------------------------------------------
-- Point-in-time reconstruction (§8) -- a filter, not a pivot.
-- ---------------------------------------------------------------------------

-- SELECT o.station_id, o.ts_utc, o.metric,
--        COALESCE(c.old_value, o.value_text) AS value_as_of
-- FROM observation o
-- LEFT JOIN LATERAL (
--     SELECT old_value FROM change_log c
--     WHERE c.station_id = o.station_id AND c.ts_utc = o.ts_utc
--       AND c.metric = o.metric AND c.changed_at > :as_of_date
--     ORDER BY c.changed_at ASC LIMIT 1
-- ) c ON true
-- WHERE o.ts_utc = :t;

-- ---------------------------------------------------------------------------
-- Adding a sensor: no migration. Two INSERTs, no ALTER, no downtime.
-- ---------------------------------------------------------------------------

-- INSERT INTO metric_catalog VALUES
--   ('soil_ch3.soilmoisture', 'instantaneous', '%', 'mean', true, NULL),
--   ('soil_ch3.ad',           'opaque',        '',  'carry', false, 'raw ADC');
-- -- observation rows then flow in with no schema change at all.
