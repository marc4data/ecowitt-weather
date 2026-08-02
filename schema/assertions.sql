-- Correctness assertions — BigQuery's replacement for CHECK/FK/trigger.
-- STATUS: not yet executed. Parse-checked as BigQuery only.
--
-- ---------------------------------------------------------------------------
-- These are NOT optional, and they are NOT equivalent to constraints.
--
-- A constraint refuses bad data at write time. An assertion notices it
-- afterwards. Everything below would have been enforced by the database in the
-- Postgres draft (commit 23054c2); on BigQuery it only holds if this file is
-- executed on every load and a failure actually fails the run.
--
-- Wire it into the Cloud Run job so that a failing ASSERT marks the run
-- 'failed' in run_log and exits non-zero (CLAUDE.md §10, fail loudly). An
-- assertion suite that runs but is ignored is worse than none, because it
-- looks like coverage.
-- ---------------------------------------------------------------------------

-- ===========================================================================
-- 1. Credentials must never reach the warehouse  (was: CHECK constraint)
-- ===========================================================================
-- §10: "Secrets never enter the repo." They must not enter storage either.
-- client.py redacts before writing; this catches a redaction regression.

ASSERT (
    SELECT COUNT(*) = 0
    FROM ecowitt.raw_payload
    WHERE DATE(requested_at) >= CURRENT_DATE() - 1
      AND (
          (STRPOS(request_url, 'application_key=') > 0
           AND STRPOS(request_url, 'application_key=REDACTED') = 0)
       OR (STRPOS(request_url, 'api_key=') > 0
           AND STRPOS(request_url, 'api_key=REDACTED') = 0)
      )
) AS 'raw_payload contains an unredacted credential — redaction has regressed';

-- ===========================================================================
-- 2. Raw landing stays append-only  (was: immutability trigger)
-- ===========================================================================
-- BigQuery cannot prevent mutation. This detects the two observable symptoms:
-- a duplicated raw_id, or a body whose recorded digest no longer matches.

ASSERT (
    SELECT COUNT(*) = 0 FROM (
        SELECT raw_id
        FROM ecowitt.raw_payload
        WHERE DATE(requested_at) >= CURRENT_DATE() - 7
        GROUP BY raw_id
        HAVING COUNT(*) > 1
    )
) AS 'raw_payload has duplicate raw_id — append-only invariant broken';

ASSERT (
    SELECT COUNT(*) = 0
    FROM ecowitt.raw_payload
    WHERE DATE(requested_at) >= CURRENT_DATE() - 1
      AND TO_HEX(SHA256(TO_JSON_STRING(body))) != body_sha256
) AS 'raw_payload body does not match its recorded digest — payload was mutated';

-- ===========================================================================
-- 3. run_log is well formed  (was: ENUM types + CHECK constraints)
-- ===========================================================================

ASSERT (
    SELECT COUNT(*) = 0
    FROM ecowitt.run_log
    WHERE DATE(started_at) >= CURRENT_DATE() - 1
      AND (trigger NOT IN ('scheduled', 'manual', 'backfill', 'reconcile')
           OR status NOT IN ('running', 'succeeded', 'failed', 'partial'))
) AS 'run_log has an invalid trigger or status value';

ASSERT (
    SELECT COUNT(*) = 0
    FROM ecowitt.run_log
    WHERE DATE(started_at) >= CURRENT_DATE() - 1
      AND status != 'running'
      AND (ended_at IS NULL OR ended_at < started_at)
) AS 'run_log has a terminal run with no end time, or ending before it started';

-- ===========================================================================
-- 4. The four resampling traps  (was: CHECK constraints on metric_catalog)
-- ===========================================================================
-- From samples/reports/metric_catalog.md. Getting any of these wrong produces
-- plausible numbers, which is the failure mode §8 warns is invisible until
-- production.

ASSERT (
    SELECT COUNT(*) = 0
    FROM ecowitt.metric_catalog
    WHERE (kind = 'circular'    AND resample_rule != 'vector_mean')
       OR (kind = 'extremum'    AND resample_rule != 'max')
       OR (kind = 'accumulator' AND resample_rule != 'last')
       OR (kind IN ('status', 'opaque') AND resamplable != FALSE)
) AS 'metric_catalog violates a resampling rule (circular/extremum/accumulator/status)';

-- wind_direction specifically. Measured: 17 north-crossings in one 24h capture,
-- each a 180-degree error under linear averaging. Named explicitly so a future
-- edit cannot quietly relax it.
ASSERT (
    SELECT COUNT(*) = 1
    FROM ecowitt.metric_catalog
    WHERE metric = 'wind.wind_direction'
      AND kind = 'circular'
      AND resample_rule = 'vector_mean'
) AS 'wind.wind_direction must be circular/vector_mean — linear averaging turns north into south';

-- ===========================================================================
-- 5. Every observed metric is classified  (was: FOREIGN KEY)
-- ===========================================================================
-- Swap the table name for observation_wide's long view under Option B.

ASSERT (
    SELECT COUNT(*) = 0
    FROM ecowitt.observation o
    LEFT JOIN ecowitt.metric_catalog c USING (metric)
    WHERE DATE(o.ts_utc) >= CURRENT_DATE() - 1
      AND c.metric IS NULL
) AS 'observation references a metric absent from metric_catalog';

-- ===========================================================================
-- 6. Idempotency actually held  (was: enforced PRIMARY KEY)
-- ===========================================================================
-- BigQuery's PRIMARY KEY is metadata for the optimizer; it permits duplicates.
-- §10 requires idempotent loads because backfill and incremental overlap, so
-- the guarantee has to be verified rather than assumed.

ASSERT (
    SELECT COUNT(*) = 0 FROM (
        SELECT station_id, ts_utc, metric
        FROM ecowitt.observation
        WHERE DATE(ts_utc) >= CURRENT_DATE() - 7
        GROUP BY station_id, ts_utc, metric
        HAVING COUNT(*) > 1
    )
) AS 'observation has duplicate (station_id, ts_utc, metric) — MERGE is not idempotent';

-- ===========================================================================
-- 7. Resolution was verified, not assumed  (D2: silent downgrade)
-- ===========================================================================
-- The single most dangerous API behaviour found in Phase 0. A run that fetched
-- 5min data must have observed 300s spacing; anything else means the API
-- downgraded and returned code=0 anyway.

ASSERT (
    SELECT COUNT(*) = 0
    FROM ecowitt.run_log
    WHERE DATE(started_at) >= CURRENT_DATE() - 1
      AND status = 'succeeded'
      AND cycle_type = '5min'
      AND (observed_delta_s IS NULL OR observed_delta_s > 360)
) AS 'a 5min run succeeded without confirming 300s spacing — silent downgrade undetected';

-- ===========================================================================
-- 8. change_log records only real changes  (was: CHECK constraint)
-- ===========================================================================

ASSERT (
    SELECT COUNT(*) = 0
    FROM ecowitt.change_log
    WHERE DATE(changed_at) >= CURRENT_DATE() - 1
      AND old_value IS NOT DISTINCT FROM new_value
      AND old_unit  IS NOT DISTINCT FROM new_unit
) AS 'change_log contains a row where nothing changed — blind upsert suspected';

-- ===========================================================================
-- 9. Synthesized values stay distinguishable  (CLAUDE.md §9)
-- ===========================================================================
-- "A synthesized value must be distinguishable from an observed one."

ASSERT (
    SELECT COUNT(*) = 0
    FROM ecowitt.observation
    WHERE DATE(ts_utc) >= CURRENT_DATE() - 1
      AND source NOT IN ('observed', 'resampled', 'backfilled')
) AS 'observation has an unknown source value';

-- A metric the catalog says is not resamplable must never appear as resampled.
-- Covers soil_chN.ad and the unitless battery status codes.
ASSERT (
    SELECT COUNT(*) = 0
    FROM ecowitt.observation o
    JOIN ecowitt.metric_catalog c USING (metric)
    WHERE DATE(o.ts_utc) >= CURRENT_DATE() - 1
      AND o.source = 'resampled'
      AND c.resamplable = FALSE
) AS 'a non-resamplable metric was resampled (opaque or status value synthesized)';

-- ===========================================================================
-- 10. Units did not drift  (CLAUDE.md §5.1, §10)
-- ===========================================================================
-- Units are pinned per request: imperial canonical, decided 2026-08-02. A unit
-- string that changes silently corrupts history in a way that is very hard to
-- detect later — so detect it here. Compared as exact bytes; ºF is U+00BA and
-- must never be normalised to U+00B0.

ASSERT (
    SELECT COUNT(*) = 0
    FROM ecowitt.observation o
    JOIN ecowitt.metric_catalog c USING (metric)
    WHERE DATE(o.ts_utc) >= CURRENT_DATE() - 1
      AND o.unit != c.canonical_unit
) AS 'observation unit differs from the pinned canonical unit — unit drift';
