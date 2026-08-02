"""Database access for the ingestion job.

One design rule shapes this file: **`run_log` is written before anything else
and closed no matter what happens.** §7 says absence of a row means the job
did not run, which is only true if a crashed run still leaves a row. So the run
opens as 'running' and a crash leaves it visibly wedged rather than invisible.

The load itself is a single transaction: staging, change_log, upsert, counts.
Either the whole pull lands or none of it does, so a partial write can never be
mistaken for a complete one.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row

from .normalize import Observation, Rejection


@dataclass
class LoadCounts:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    rejected: int = 0

    @property
    def fetched(self) -> int:
        return self.inserted + self.updated + self.unchanged + self.rejected


def connect(dsn: str) -> psycopg.Connection:
    return psycopg.connect(dsn, row_factory=dict_row, autocommit=False)


@contextmanager
def run_logged(
    conn: psycopg.Connection,
    *,
    trigger: str,
    mode: str,
    window_start: datetime | None,
    window_end: datetime | None,
    cycle_type: str | None,
):
    """Open a run_log row, and close it however the run ends.

    Yields a mutable dict the caller fills in. On an exception the row is
    marked 'failed' with the error detail and the exception is re-raised, so
    the job still exits non-zero (§10, fail loudly).
    """
    run_id = str(uuid.uuid4())
    state: dict[str, Any] = {
        "run_id": run_id,
        "counts": LoadCounts(),
        "observed_delta_s": None,
    }

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO run_log (run_id, trigger, mode, window_start_utc,
                                 window_end_utc, cycle_type, status, started_at)
            VALUES (%s, %s, %s, %s, %s, %s, 'running', now())
            """,
            (run_id, trigger, mode, window_start, window_end, cycle_type),
        )
    conn.commit()  # visible immediately, so a crash leaves a wedged row

    try:
        yield state
    except Exception as exc:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE run_log SET status='failed', ended_at=now(), error_detail=%s
                WHERE run_id=%s
                """,
                (f"{type(exc).__name__}: {exc}"[:4000], run_id),
            )
        conn.commit()
        raise

    counts: LoadCounts = state["counts"]
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE run_log
               SET status='succeeded', ended_at=now(),
                   observed_delta_s=%s,
                   rows_fetched=%s, rows_inserted=%s, rows_updated=%s,
                   rows_unchanged=%s, rows_rejected=%s
             WHERE run_id=%s
            """,
            (
                state["observed_delta_s"],
                counts.fetched,
                counts.inserted,
                counts.updated,
                counts.unchanged,
                counts.rejected,
                run_id,
            ),
        )
    conn.commit()


def land_raw(
    conn: psycopg.Connection,
    *,
    run_id: str,
    endpoint: str,
    label: str,
    requested_at: datetime,
    request_url: str,
    http_status: int,
    api_code: Any,
    api_message: Any,
    body_bytes: bytes,
    duration_s: float,
) -> int:
    """Land the payload verbatim, before anything parses it.

    §10: parsing bugs are recoverable, discarded data is not. This is committed
    on its own so that a later normalisation failure still leaves the raw
    response on disk in the database.
    """
    digest = hashlib.sha256(body_bytes).hexdigest()
    try:
        body_json = json.loads(body_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError):
        # Still land it. A body that is not JSON is exactly the case where the
        # raw copy matters most.
        body_json = {"_unparseable": True, "_bytes": len(body_bytes)}

    with conn.cursor() as cur:
        cur.execute(
            """
            -- raw_id is GENERATED ALWAYS AS IDENTITY: the database owns it.
            INSERT INTO raw_payload (run_id, endpoint, label, requested_at,
                                     request_url, http_status, api_code, api_message,
                                     body, body_sha256, body_bytes, duration_s)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING raw_id
            """,
            (
                run_id,
                endpoint,
                label,
                requested_at,
                request_url,
                http_status,
                None if api_code is None else str(api_code),
                None if api_message is None else str(api_message),
                json.dumps(body_json),
                bytes.fromhex(digest),
                len(body_bytes),
                round(duration_s, 4),
            ),
        )
        raw_id = cur.fetchone()["raw_id"]
    conn.commit()
    return raw_id


def load_observations(
    conn: psycopg.Connection,
    observations: list[Observation],
    *,
    run_id: str,
) -> LoadCounts:
    """Idempotent load with change detection, in one transaction.

    §7 forbids a blind upsert and requires 'unchanged' to be a countable
    outcome. The WHERE on DO UPDATE delivers both: identical rows conflict,
    fail the predicate, and return nothing — so they are counted rather than
    rewritten, and a reconciliation run that reports thousands of updates is a
    signal rather than noise.
    """
    counts = LoadCounts()
    if not observations:
        return counts

    rows = [
        (
            o.station_id,
            o.ts_utc,
            o.metric,
            o.value_text,
            o.value_num,
            o.unit,
            o.source,
            run_id,
            run_id,
        )
        for o in observations
    ]

    with conn.cursor() as cur:
        cur.execute("""
            CREATE TEMP TABLE staging (
                station_id text, ts_utc timestamptz, metric text,
                value_text text, value_num double precision, unit text,
                source observation_source, first_seen_run uuid, last_seen_run uuid
            ) ON COMMIT DROP
        """)
        with cur.copy(
            "COPY staging (station_id, ts_utc, metric, value_text, value_num,"
            " unit, source, first_seen_run, last_seen_run) FROM STDIN"
        ) as copy:
            for row in rows:
                copy.write_row(row)

        # change_log BEFORE the upsert, while the old values still exist.
        # This is the mechanism §8 relies on for point-in-time reconstruction.
        cur.execute(
            """
            INSERT INTO change_log (station_id, ts_utc, metric, old_value, new_value,
                                    old_unit, new_unit, run_id, reason)
            SELECT o.station_id, o.ts_utc, o.metric, o.value_text, s.value_text,
                   o.unit, s.unit, %s, 'value differed on re-fetch'
              FROM staging s
              JOIN observation o USING (station_id, ts_utc, metric)
             WHERE o.value_text IS DISTINCT FROM s.value_text
                OR o.unit       IS DISTINCT FROM s.unit
            """,
            (run_id,),
        )

        cur.execute("""
            INSERT INTO observation AS o
                (station_id, ts_utc, metric, value_text, value_num, unit,
                 source, first_seen_run, last_seen_run, updated_at)
            SELECT station_id, ts_utc, metric, value_text, value_num, unit,
                   source, first_seen_run, last_seen_run, now()
              FROM staging
            ON CONFLICT (station_id, ts_utc, metric) DO UPDATE
               SET value_text    = EXCLUDED.value_text,
                   value_num     = EXCLUDED.value_num,
                   unit          = EXCLUDED.unit,
                   source        = EXCLUDED.source,
                   last_seen_run = EXCLUDED.last_seen_run,
                   updated_at    = now()
             WHERE o.value_text IS DISTINCT FROM EXCLUDED.value_text
                OR o.unit       IS DISTINCT FROM EXCLUDED.unit
            RETURNING (xmax = 0) AS was_insert
        """)
        # xmax = 0 distinguishes an insert from an update. Rows that conflicted
        # but failed the WHERE return nothing at all -- those are the unchanged.
        results = cur.fetchall()

    counts.inserted = sum(1 for r in results if r["was_insert"])
    counts.updated = len(results) - counts.inserted
    counts.unchanged = len(observations) - len(results)
    conn.commit()
    return counts


def quarantine(
    conn: psycopg.Connection, rejections: list[Rejection], *, run_id: str, raw_id: int | None
) -> int:
    """Rejected rows are quarantined, not dropped (§10)."""
    if not rejections:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO quarantine (run_id, raw_id, station_id, ts_utc, metric,
                                    value_text, unit, reason, quarantined_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s, now())
            """,
            [
                (run_id, raw_id, r.station_id, r.ts_utc, r.metric, r.value_text, r.unit, r.reason)
                for r in rejections
            ],
        )
    conn.commit()
    return len(rejections)


def latest_observation(conn: psycopg.Connection, station_id: str) -> datetime | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT max(ts_utc) AS ts FROM observation WHERE station_id = %s",
            (station_id,),
        )
        row = cur.fetchone()
    return row["ts"] if row else None


def missing_slots(
    conn: psycopg.Connection, station_id: str, since: datetime, until: datetime
) -> list[datetime]:
    """5-minute grid slots with no observation at all.

    Drives the gap sweep. Gaps are routine on this station -- 281 of 289
    expected points in a normal day -- so this is a work-list, not an alarm.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT g.slot
              FROM generate_series(%s, %s, interval '5 minutes') AS g(slot)
             WHERE NOT EXISTS (
                   SELECT 1 FROM observation o
                    WHERE o.station_id = %s AND o.ts_utc = g.slot)
             ORDER BY g.slot
            """,
            (since, until, station_id),
        )
        return [r["slot"] for r in cur.fetchall()]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
