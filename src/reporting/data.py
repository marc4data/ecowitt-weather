"""Database access for the daily email: two connections, on purpose.

§8.4 requires the report to be read-only against the observation data, and
`email_log` to have its own narrowly-granted writer rather than widening
`ecowitt_ro`. So there are two roles and two connections:

  read      ecowitt_ro          SELECT only, `default_transaction_read_only`
  write     ecowitt_emailer     INSERT/SELECT on `email_log` and nothing else

On a workstation both fall back to the notebooks' tunnel, which is the only
route to a database that binds to localhost on a VM accepting no inbound
connections. On the VM `infra/run_report.sh` sets both DSNs from Secret
Manager and no tunnel is involved at all.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import date, datetime

from sqlalchemy import create_engine, text

from . import config
from .shared import nb


def connect_read():
    """A read-only connection to the observation data.

    Not closed by this module when it comes from the notebooks' helper: that
    connection is shared infrastructure with its own lifecycle (and its own
    tunnel-ownership rules), and closing it here would pull it out from under an
    open notebook.
    """
    dsn = os.environ.get(config.ENV_READ_DSN)
    if not dsn:
        return nb.ensure_db()
    return create_engine(dsn, connect_args={"connect_timeout": 10}).connect()


@contextmanager
def email_log_writer():
    """The `email_log` writer, or None when it is not configured.

    Yields None rather than raising. A report that cannot record that it was
    sent is a degraded report; a report that refuses to send because it cannot
    record it would be an alerting path that fails closed in the wrong
    direction. The caller falls back to the JSONL log, which is always written.
    """
    dsn = os.environ.get(config.ENV_EMAIL_LOG_DSN)
    if not dsn:
        # On a workstation the read connection is a superset in practice --
        # except that it is read-only, so it genuinely cannot write. Say so
        # rather than pretending.
        yield None
        return
    engine = create_engine(dsn, connect_args={"connect_timeout": 10})
    conn = engine.connect()
    try:
        yield conn
    finally:
        conn.close()
        engine.dispose()


def already_sent(conn, for_date: date, mode: str) -> bool:
    """Has this exact (day, mode) already gone out?

    Keyed on BOTH, never on the date alone (§5.6): a test send must not block
    that day's production send, and vice versa. Returns False when there is no
    writer connection -- an unknown answer must not suppress the email.
    """
    if conn is None:
        return False
    row = conn.execute(
        text("SELECT count(*) FROM email_log WHERE for_date = :d AND mode = :m"),
        {"d": for_date, "m": mode},
    ).scalar()
    return bool(row)


def record_sent(
    conn,
    *,
    for_date: date,
    mode: str,
    severity: str,
    recipients: list[str],
    message_id: str,
    sent_at: datetime | None = None,
) -> bool:
    """Write the `email_log` row. Returns whether it was written.

    Never raises: this runs after a successful send, and an exception here would
    turn a delivered email into a crashed job.
    """
    if conn is None:
        return False
    try:
        conn.execute(
            text("""
                INSERT INTO email_log (sent_at, for_date, mode, severity,
                                       recipients, message_id)
                VALUES (coalesce(:sent_at, now()), :for_date, :mode, :severity,
                        :recipients, :message_id)
            """),
            {
                "sent_at": sent_at,
                "for_date": for_date,
                "mode": mode,
                "severity": severity,
                "recipients": ",".join(recipients),
                "message_id": message_id,
            },
        )
        conn.commit()
        return True
    except Exception as exc:  # never raise from the send path
        print(f"WARNING: could not write email_log ({type(exc).__name__}: {exc})")
        return False
