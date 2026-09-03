-- Phase 2 schema: the record that the daily email went out.
-- Apply after 00_common.sql and option_a_long.sql.
-- STATUS: NOT YET EXECUTED. Parse-checked only.
--
-- ---------------------------------------------------------------------------
-- Why this table exists at all
--
-- §7's principle, applied to the email: a run that changed nothing still writes
-- a row, so ABSENCE of a row is what tells you the job did not run. The email
-- that never arrives is the hardest failure to see -- a dead scheduler produces
-- no errors, just silence and a green dashboard -- and this table is what
-- `heartbeat.sh` reads to turn that silence into a Cloud Logging alert.
--
-- ---------------------------------------------------------------------------
-- Why `mode` is part of the record and not just the timestamp
--
-- Two consequences, both load-bearing:
--
--   1. Idempotency keys on (for_date, mode), so a test send does not consume
--      that day's production send.
--   2. The heartbeat's staleness query filters `WHERE mode = 'production'`.
--      Without that filter, a test run at 3pm resets the clock and masks a
--      production email that never went out -- an observability check defeated
--      by the act of testing it, which is worse than not having the check.
-- ---------------------------------------------------------------------------

CREATE TABLE email_log (
    email_id   bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sent_at    timestamptz NOT NULL DEFAULT now(),
    for_date   date        NOT NULL,
    mode       text        NOT NULL,
    severity   text        NOT NULL,
    -- Comma-separated rather than an array: this is a record of what was
    -- actually put in the To: header, and it is read by humans diagnosing "who
    -- got that email", not joined against anything.
    recipients text        NOT NULL,
    message_id text        NOT NULL,

    CONSTRAINT email_log_known_mode
        CHECK (mode IN ('production', 'test')),
    CONSTRAINT email_log_known_severity
        CHECK (severity IN ('ok', 'warn', 'alert')),
    -- Idempotency is structural, not procedural -- the same argument
    -- `observation`'s primary key makes. The application also checks before
    -- sending, but a second process, a manual re-run or a retried timer simply
    -- cannot produce two production emails for one day.
    CONSTRAINT email_log_one_per_day_per_mode UNIQUE (for_date, mode),
    -- A report always describes a finished day, never today.
    CONSTRAINT email_log_reports_a_past_day
        CHECK (for_date < (sent_at AT TIME ZONE 'America/Chicago')::date)
);

-- The heartbeat's staleness query, exactly: newest production row.
CREATE INDEX email_log_production_recent
    ON email_log (sent_at DESC) WHERE mode = 'production';

-- ---------------------------------------------------------------------------
-- The writer role (§8.4)
--
-- The report reads the observation data as `ecowitt_ro`, which is SELECT-only
-- with `default_transaction_read_only` forced on -- and must stay that way.
-- Widening it so one table could be written would give every exploratory GUI
-- session write access to `observation`, which §8 exists to prevent.
--
-- So `email_log` gets its own role, and that role can touch nothing else.
-- ---------------------------------------------------------------------------

-- Run as a superuser; the password comes from Secret Manager, never a literal.
--
--   CREATE ROLE ecowitt_emailer LOGIN PASSWORD :'pw';
--   GRANT CONNECT ON DATABASE ecowitt TO ecowitt_emailer;
--   GRANT USAGE ON SCHEMA public TO ecowitt_emailer;
--
-- SELECT as well as INSERT: the duplicate check reads this table before the
-- send, and a writer that cannot read its own table would have to send first
-- and ask afterwards.
--
--   GRANT SELECT, INSERT ON email_log TO ecowitt_emailer;
--   GRANT USAGE ON SEQUENCE email_log_email_id_seq TO ecowitt_emailer;
--
-- Deliberately NOT granted: UPDATE and DELETE. The log of what was sent is
-- append-only for the same reason `raw_payload` is -- it is evidence.
--
--   REVOKE CREATE ON SCHEMA public FROM ecowitt_emailer;
