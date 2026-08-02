-- Phase 1 schema, part 1 of 2: tables shared by BOTH curated-table options.
-- Target: BigQuery, dataset location us-central1 (decided 2026-08-02).
--
-- STATUS: not yet executed. Parse-checked as BigQuery only.
--
-- ---------------------------------------------------------------------------
-- READ THIS FIRST: what changed when we moved off Postgres
--
-- The Postgres draft (commit 23054c2) enforced five of CLAUDE.md's rules as
-- database constraints. BigQuery has none of those mechanisms:
--
--   | rule                          | Postgres        | BigQuery              |
--   |-------------------------------|-----------------|-----------------------|
--   | raw payload is immutable      | trigger, RAISEs | convention + detection|
--   | no unredacted credential      | CHECK           | assertion query       |
--   | idempotent load               | enforced PK     | NOT ENFORCED PK, MERGE|
--   | metric must be classified     | FOREIGN KEY     | assertion query       |
--   | resampling traps              | CHECK           | assertion query       |
--
-- Correctness therefore moves from the schema into `assertions.sql`, which
-- MUST run as part of every load. A constraint refuses bad data; an assertion
-- only reports it afterwards. That is a genuine downgrade, accepted knowingly
-- in exchange for ~$0/month, and it is why the assertions are not optional.
-- ---------------------------------------------------------------------------

CREATE SCHEMA IF NOT EXISTS ecowitt
    OPTIONS (location = 'us-central1', description = 'Ecowitt weather pipeline');

-- ---------------------------------------------------------------------------
-- run_log (CLAUDE.md §7)
--
-- "A run that changed nothing still writes a row. Absence of a row means the
-- job didn't run." Written at start with status 'running', updated on finish,
-- so a crashed job leaves a visible 'running' row rather than no row.
--
-- No ENUM type in BigQuery: trigger/status/mode are STRING, and their allowed
-- values are checked in assertions.sql instead.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ecowitt.run_log (
    run_id           STRING    NOT NULL,
    trigger          STRING    NOT NULL,  -- scheduled|manual|backfill|reconcile
    mode             STRING    NOT NULL,
    window_start_utc TIMESTAMP,
    window_end_utc   TIMESTAMP,
    cycle_type       STRING,
    -- What the API actually returned, not what was asked for. D2 proved
    -- cycle_type is silently downgraded past a 24h span, so the observed
    -- spacing must be recorded and compared, never assumed.
    observed_delta_s INT64,
    started_at       TIMESTAMP NOT NULL,
    ended_at         TIMESTAMP,
    status           STRING    NOT NULL,  -- running|succeeded|failed|partial
    rows_fetched     INT64     NOT NULL,
    rows_inserted    INT64     NOT NULL,
    rows_updated     INT64     NOT NULL,
    rows_unchanged   INT64     NOT NULL,
    rows_rejected    INT64     NOT NULL,
    error_detail     STRING,

    PRIMARY KEY (run_id) NOT ENFORCED
)
PARTITION BY DATE(started_at)
OPTIONS (description = 'One row per execution. Absence of a row means no run.');

-- ---------------------------------------------------------------------------
-- raw_payload (CLAUDE.md §8, §10)
--
-- "Never discard raw payloads." "Raw landing is append-only and immutable."
--
-- ⚠️ BigQuery cannot enforce append-only. There is no trigger, and IAM has no
-- insert-without-delete role — bigquery.dataEditor grants both. Immutability
-- is therefore a convention, backed by:
--   * body_sha256, so a mutated row is detectable
--   * assertions.sql checking that no (raw_id, body_sha256) pair ever changes
--   * 7-day time travel, which can recover an accidental mutation
-- Detection, not prevention. Do not mistake one for the other.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ecowitt.raw_payload (
    raw_id       STRING    NOT NULL,      -- uuid; no sequences in BigQuery
    run_id       STRING    NOT NULL,
    endpoint     STRING    NOT NULL,
    label        STRING    NOT NULL,
    requested_at TIMESTAMP NOT NULL,
    request_url  STRING    NOT NULL,      -- credentials redacted; asserted
    http_status  INT64     NOT NULL,
    api_code     STRING,
    api_message  STRING,
    body         JSON      NOT NULL,
    body_sha256  STRING    NOT NULL,
    body_bytes   INT64     NOT NULL,
    duration_s   NUMERIC,

    PRIMARY KEY (raw_id) NOT ENFORCED,
    FOREIGN KEY (run_id) REFERENCES ecowitt.run_log (run_id) NOT ENFORCED
)
PARTITION BY DATE(requested_at)
OPTIONS (
    description = 'Append-only landing zone. NEVER mutate. See assertions.sql.',
    require_partition_filter = TRUE
);

-- ---------------------------------------------------------------------------
-- metric_catalog (samples/reports/metric_catalog.md)
--
-- In Postgres the four resampling traps were CHECK constraints. Here they are
-- columns whose consistency assertions.sql verifies.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ecowitt.metric_catalog (
    metric         STRING  NOT NULL,
    -- instantaneous|derived|circular|extremum|accumulator|opaque|diagnostic|status
    kind           STRING  NOT NULL,
    canonical_unit STRING  NOT NULL,
    -- mean|recompute|vector_mean|max|last|carry
    resample_rule  STRING  NOT NULL,
    resamplable    BOOL    NOT NULL,
    notes          STRING,

    PRIMARY KEY (metric) NOT ENFORCED
)
OPTIONS (description = 'Per-metric semantics. Load before any observation row.');

-- ---------------------------------------------------------------------------
-- change_log (CLAUDE.md §7, §8)
-- The mechanism for point-in-time reconstruction.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ecowitt.change_log (
    change_id  STRING    NOT NULL,       -- uuid
    station_id STRING    NOT NULL,
    ts_utc     TIMESTAMP NOT NULL,
    metric     STRING    NOT NULL,
    old_value  STRING,
    new_value  STRING,
    old_unit   STRING,
    new_unit   STRING,
    run_id     STRING    NOT NULL,
    changed_at TIMESTAMP NOT NULL,
    reason     STRING    NOT NULL,

    PRIMARY KEY (change_id) NOT ENFORCED,
    FOREIGN KEY (run_id) REFERENCES ecowitt.run_log (run_id) NOT ENFORCED
)
PARTITION BY DATE(changed_at)
CLUSTER BY station_id, metric, ts_utc
OPTIONS (description = 'Field-level audit trail. Clustered for §8 lookups.');

-- ---------------------------------------------------------------------------
-- quarantine (CLAUDE.md §10)
-- "Rejected rows are quarantined, not dropped."
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ecowitt.quarantine (
    quarantine_id  STRING    NOT NULL,
    run_id         STRING    NOT NULL,
    raw_id         STRING,
    station_id     STRING,
    ts_utc         TIMESTAMP,
    metric         STRING,
    value_text     STRING,
    unit           STRING,
    reason         STRING    NOT NULL,
    quarantined_at TIMESTAMP NOT NULL,

    PRIMARY KEY (quarantine_id) NOT ENFORCED
)
PARTITION BY DATE(quarantined_at)
CLUSTER BY reason;
