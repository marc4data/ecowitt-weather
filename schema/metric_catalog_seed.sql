-- Seed data for metric_catalog — the 42 metrics this station reports.
-- STATUS: EXECUTED 2026-08-02 against ecowitt-db (PostgreSQL 16.14).
--
-- Derived from samples/reports/metric_catalog.md, which is derived from the
-- Phase 0 captures. Load this BEFORE any observation row: observation carries
-- a composite FK (metric, unit) -> metric_catalog (metric, canonical_unit),
-- so an unclassified metric or a drifted unit simply cannot be inserted.
--
-- ⚠️ UNIT STRINGS ARE EXACT BYTES. 'ºF' is U+00BA MASCULINE ORDINAL INDICATOR
-- followed by F -- NOT U+00B0 DEGREE SIGN, and not U+2109. Wind direction is a
-- bare U+00BA. Solar is 'W/m²' with U+00B2. These are what the API actually
-- returns; normalising any of them breaks the FK and silently rewrites history.
--
-- Units are the imperial set pinned 2026-08-02: temp_unitid=2, pressure=4,
-- wind=9, rainfall=13, solar=16.

INSERT INTO metric_catalog (metric, kind, canonical_unit, resample_rule, resamplable, notes) VALUES
-- outdoor: two measured, four computed by Ecowitt from them
('outdoor.temperature',      'instantaneous', 'ºF',    'mean',        true,  NULL),
('outdoor.humidity',         'instantaneous', '%',     'mean',        true,  NULL),
('outdoor.feels_like',       'derived',       'ºF',    'recompute',   true,  'from temperature + humidity'),
('outdoor.app_temp',         'derived',       'ºF',    'recompute',   true,  'apparent temperature'),
('outdoor.dew_point',        'derived',       'ºF',    'recompute',   true,  NULL),
('outdoor.vpd',              'derived',       'inHg',  'recompute',   true,  'vapour pressure deficit; absent from published docs'),

-- indoor: same shape. app_tempin is the vendor spelling, not a typo.
('indoor.temperature',       'instantaneous', 'ºF',    'mean',        true,  NULL),
('indoor.humidity',          'instantaneous', '%',     'mean',        true,  NULL),
('indoor.dew_point',         'derived',       'ºF',    'recompute',   true,  NULL),
('indoor.feels_like',        'derived',       'ºF',    'recompute',   true,  NULL),
('indoor.app_tempin',        'derived',       'ºF',    'recompute',   true,  'vendor spelling; absent from published docs'),

('pressure.absolute',        'instantaneous', 'inHg',  'mean',        true,  'station pressure'),
('pressure.relative',        'instantaneous', 'inHg',  'mean',        true,  'identical to absolute in all Phase 0 captures - console altitude offset appears unset'),

-- wind: three metrics, three DIFFERENT resampling rules. See §9.
('wind.wind_speed',          'instantaneous', 'mph',   'mean',        true,  'already an interval average'),
('wind.wind_gust',           'extremum',      'mph',   'max',         true,  'per-interval MAX; a mean understates peak wind'),
('wind.wind_direction',      'circular',      'º',     'vector_mean', true,  'CIRCULAR. 17 north-crossings in one 24h capture, each a 180deg error under linear averaging'),

('solar_and_uvi.solar',      'instantaneous', 'W/m²',  'mean',        true,  NULL),
('solar_and_uvi.uvi',        'instantaneous', '',      'mean',        true,  'dimensionless index'),

-- rainfall: only rain_rate is instantaneous; the rest are resetting totals
('rainfall_piezo.rain_rate', 'instantaneous', 'in/hr', 'mean',        true,  'only instantaneous rainfall metric'),
('rainfall_piezo.event',     'accumulator',   'in',    'last',        true,  'resets per event'),
('rainfall_piezo.1_hour',    'accumulator',   'in',    'last',        true,  'docs call this hourly; the wire name is 1_hour'),
('rainfall_piezo.daily',     'accumulator',   'in',    'last',        true,  NULL),
('rainfall_piezo.weekly',    'accumulator',   'in',    'last',        true,  NULL),
('rainfall_piezo.monthly',   'accumulator',   'in',    'last',        true,  NULL),
('rainfall_piezo.yearly',    'accumulator',   'in',    'last',        true,  NULL),

('temp_and_humidity_ch1.temperature', 'instantaneous', 'ºF', 'mean',  true,  NULL),
('temp_and_humidity_ch1.humidity',    'instantaneous', '%',  'mean',  true,  NULL),
('temp_and_humidity_ch2.temperature', 'instantaneous', 'ºF', 'mean',  true,  NULL),
('temp_and_humidity_ch2.humidity',    'instantaneous', '%',  'mean',  true,  NULL),
('temp_and_humidity_ch3.temperature', 'instantaneous', 'ºF', 'mean',  true,  NULL),
('temp_and_humidity_ch3.humidity',    'instantaneous', '%',  'mean',  true,  NULL),

('soil_ch1.soilmoisture',    'instantaneous', '%',     'mean',        true,  NULL),
('soil_ch2.soilmoisture',    'instantaneous', '%',     'mean',        true,  NULL),
-- Decided 2026-08-02: keep, as an opaque integer. Never interpolated.
('soil_ch1.ad',              'opaque',        '',      'carry',       false, 'raw ADC-style reading; relationship to soilmoisture inferred, not observed'),
('soil_ch2.ad',              'opaque',        '',      'carry',       false, 'raw ADC-style reading; relationship to soilmoisture inferred, not observed'),

-- battery is two different kinds of thing sharing a group name
('battery.haptic_array_battery',    'diagnostic', 'V', 'last',        true,  NULL),
('battery.haptic_array_capacitor',  'diagnostic', 'V', 'last',        true,  NULL),
('battery.soilmoisture_sensor_ch1', 'diagnostic', 'V', 'last',        true,  NULL),
('battery.soilmoisture_sensor_ch2', 'diagnostic', 'V', 'last',        true,  NULL),
-- Unitless status codes. Not measurements: a mean of two status codes is
-- meaningless, so resamplable is false and the CHECK enforces it.
('battery.temp_humidity_sensor_ch1', 'status', '', 'last', false, 'real-time only; absent from history'),
('battery.temp_humidity_sensor_ch2', 'status', '', 'last', false, 'real-time only; absent from history'),
('battery.temp_humidity_sensor_ch3', 'status', '', 'last', false, 'real-time only; absent from history')
ON CONFLICT (metric) DO NOTHING;
