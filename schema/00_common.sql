-- Phase 1 schema, part 1 of 2: tables shared by BOTH curated-table options.
-- Target: self-managed PostgreSQL 16 on a GCP e2-micro VM, us-central1
-- (decided 2026-08-02). Vanilla Postgres -- nothing here is Cloud SQL specific.
--
-- STATUS: EXECUTED 2026-08-02 against ecowitt-db (PostgreSQL 16.14), applied
-- with ON_ERROR_STOP=1, 21 statements, no errors. All six constraints were
-- then verified to reject their violations -- see verify_constraints.sql.
--
-- Everything here is independent of the long-vs-wide decision.

-- ---------------------------------------------------------------------------
-- run_log (CLAUDE.md §7)
--
-- "A run that changed nothing still writes a row. Absence of a row means the
-- job didn't run." That distinction is the whole point, so the row is written
-- at start with status 'running' and updated on completion -- a crashed job
-- leaves a visible 'running' row rather than no row at all.
-- ---------------------------------------------------------------------------

CREATE TYPE run_trigger AS ENUM ('scheduled', 'manual', 'backfill', 'reconcile');
CREATE TYPE run_status  AS ENUM ('running', 'succeeded', 'failed', 'partial');

CREATE TABLE run_log (
    run_id            uuid        PRIMARY KEY,
    trigger           run_trigger NOT NULL,
    mode              text        NOT NULL,
    window_start_utc  timestamptz,
    window_end_utc    timestamptz,
    cycle_type        text,
    -- What the API actually returned, not what we asked for (D2: silent
    -- downgrade). Phase 1 must compare these two and fail on mismatch.
    observed_delta_s  integer,
    started_at        timestamptz NOT NULL DEFAULT now(),
    ended_at          timestamptz,
    status            run_status  NOT NULL DEFAULT 'running',
    rows_fetched      integer     NOT NULL DEFAULT 0,
    rows_inserted     integer     NOT NULL DEFAULT 0,
    rows_updated      integer     NOT NULL DEFAULT 0,
    rows_unchanged    integer     NOT NULL DEFAULT 0,
    rows_rejected     integer     NOT NULL DEFAULT 0,
    error_detail      text,

    CONSTRAINT run_log_ends_after_start
        CHECK (ended_at IS NULL OR ended_at >= started_at),
    CONSTRAINT run_log_terminal_has_end
        CHECK (status = 'running' OR ended_at IS NOT NULL),
    CONSTRAINT run_log_window_ordered
        CHECK (window_start_utc IS NULL OR window_end_utc IS NULL
               OR window_start_utc <= window_end_utc),
    -- D2: cycle_type=5min is silently downgraded past a 24h span, with code=0.
    -- A run may not claim success at 5min without having measured the spacing
    -- it actually got. Makes the most dangerous API behaviour unrecordable
    -- rather than merely detectable.
    CONSTRAINT run_log_5min_spacing_verified
        CHECK (status <> 'succeeded' OR cycle_type IS DISTINCT FROM '5min'
               OR (observed_delta_s IS NOT NULL AND observed_delta_s <= 360))
);

CREATE INDEX run_log_started ON run_log (started_at DESC);
CREATE INDEX run_log_unfinished ON run_log (status) WHERE status = 'running';

-- ---------------------------------------------------------------------------
-- raw_payload (CLAUDE.md §8, §10)
--
-- "Never discard raw payloads." "Raw landing is append-only and immutable."
-- Immutability is enforced by a trigger that RAISES rather than a rule that
-- silently discards -- §10 requires failing loudly.
-- ---------------------------------------------------------------------------

CREATE TABLE raw_payload (
    raw_id       bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id       uuid        NOT NULL REFERENCES run_log (run_id),
    endpoint     text        NOT NULL,
    label        text        NOT NULL,
    requested_at timestamptz NOT NULL,
    request_url  text        NOT NULL,
    http_status  integer     NOT NULL,
    api_code     text,
    api_message  text,
    body         jsonb       NOT NULL,
    body_sha256  bytea       NOT NULL,
    body_bytes   integer     NOT NULL,
    duration_s   numeric(10, 4),

    -- §10: "Secrets never enter the repo." They must not enter the database
    -- either. A redaction bug becomes a constraint violation, not a leak.
    CONSTRAINT raw_payload_url_redacted CHECK (
        (position('application_key=' in request_url) = 0
         OR position('application_key=REDACTED' in request_url) > 0)
        AND
        (position('api_key=' in request_url) = 0
         OR position('api_key=REDACTED' in request_url) > 0)
    )
);

CREATE INDEX raw_payload_run ON raw_payload (run_id);
CREATE INDEX raw_payload_requested ON raw_payload (requested_at DESC);
-- Same body landed twice (overlapping incremental + backfill) is detectable.
CREATE INDEX raw_payload_digest ON raw_payload (body_sha256);

CREATE FUNCTION raw_payload_is_immutable() RETURNS trigger
    LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION
        'raw_payload is append-only (CLAUDE.md §8): % denied on raw_id=%',
        TG_OP, OLD.raw_id;
END;
$$;

CREATE TRIGGER raw_payload_no_mutate
    BEFORE UPDATE OR DELETE ON raw_payload
    FOR EACH ROW EXECUTE FUNCTION raw_payload_is_immutable();

-- ---------------------------------------------------------------------------
-- metric_catalog (samples/reports/metric_catalog.md)
--
-- The catalog is data, not code, so the resampler cannot silently disagree
-- with the documented rules and curated rows cannot reference a metric whose
-- semantics were never classified.
-- ---------------------------------------------------------------------------

CREATE TYPE metric_kind AS ENUM (
    'instantaneous',  -- point-in-time reading; mean over the slot
    'derived',        -- Ecowitt-computed; recompute, never resample
    'circular',       -- degrees; vector mean, NEVER linear
    'extremum',       -- per-interval max; max, never mean
    'accumulator',    -- running total that resets; last, diff within epoch
    'opaque',         -- meaning not established; carry, never interpolate
    'diagnostic',     -- hardware health, not weather
    'status'          -- unitless code; no arithmetic, ever
);

CREATE TABLE metric_catalog (
    metric         text        PRIMARY KEY,
    kind           metric_kind NOT NULL,
    canonical_unit text        NOT NULL,
    resample_rule  text        NOT NULL,
    resamplable    boolean     NOT NULL,
    notes          text,

    -- The four traps in the catalog, enforced rather than documented.
    CONSTRAINT metric_circular_needs_vector_mean
        CHECK (kind <> 'circular' OR resample_rule = 'vector_mean'),
    CONSTRAINT metric_extremum_needs_max
        CHECK (kind <> 'extremum' OR resample_rule = 'max'),
    CONSTRAINT metric_accumulator_needs_last
        CHECK (kind <> 'accumulator' OR resample_rule = 'last'),
    CONSTRAINT metric_status_and_opaque_not_resamplable
        CHECK (kind NOT IN ('status', 'opaque') OR resamplable = false),
    -- Target for the composite FK from observation(metric, unit). Units are
    -- pinned per request (imperial, decided 2026-08-02); §10 warns a silent
    -- unit change corrupts history in a way that is very hard to detect later.
    -- This makes it impossible to store rather than merely hard to detect.
    CONSTRAINT metric_catalog_metric_unit UNIQUE (metric, canonical_unit)
);

-- ---------------------------------------------------------------------------
-- change_log (CLAUDE.md §7, §8)
--
-- The mechanism for point-in-time reconstruction: "what did the record for
-- timestamp T look like as of date D?"
-- ---------------------------------------------------------------------------

CREATE TABLE change_log (
    change_id  bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    station_id text        NOT NULL,
    ts_utc     timestamptz NOT NULL,
    metric     text        NOT NULL REFERENCES metric_catalog (metric),
    old_value  text,
    new_value  text,
    old_unit   text,
    new_unit   text,
    run_id     uuid        NOT NULL REFERENCES run_log (run_id),
    changed_at timestamptz NOT NULL DEFAULT now(),
    reason     text        NOT NULL,

    CONSTRAINT change_log_something_changed
        CHECK (old_value IS DISTINCT FROM new_value
               OR old_unit IS DISTINCT FROM new_unit)
);

-- Supports the §8 question directly: filter to a natural key, order by
-- changed_at, take everything at or before D.
CREATE INDEX change_log_point_in_time
    ON change_log (station_id, metric, ts_utc, changed_at DESC);
CREATE INDEX change_log_run ON change_log (run_id);

-- ---------------------------------------------------------------------------
-- quarantine (CLAUDE.md §10)
-- "Rejected rows are quarantined, not dropped."
-- ---------------------------------------------------------------------------

CREATE TABLE quarantine (
    quarantine_id bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id        uuid        NOT NULL REFERENCES run_log (run_id),
    raw_id        bigint      REFERENCES raw_payload (raw_id),
    station_id    text,
    ts_utc        timestamptz,
    metric        text,
    value_text    text,
    unit          text,
    reason        text        NOT NULL,
    quarantined_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX quarantine_run ON quarantine (run_id);
CREATE INDEX quarantine_reason ON quarantine (reason);

-- ---------------------------------------------------------------------------
-- backup_log
--
-- §7's principle applied to backups: a run that succeeded still writes a row,
-- so absence of a row distinguishes "the backup failed" from "the backup never
-- started". Self-managing the database means backups are now part of the
-- system's correctness, not an ops detail outside it.
-- ---------------------------------------------------------------------------

CREATE TABLE backup_log (
    backup_id        bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    finished_at      timestamptz NOT NULL DEFAULT now(),
    object_uri       text        NOT NULL,
    bytes            bigint      NOT NULL,
    observation_rows bigint      NOT NULL,

    CONSTRAINT backup_log_not_empty CHECK (bytes > 0)
);

CREATE INDEX backup_log_recent ON backup_log (finished_at DESC);
