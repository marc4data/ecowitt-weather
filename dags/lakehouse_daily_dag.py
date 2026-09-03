"""Airflow DAG: the daily lakehouse email, on the Mac.

WHY THIS EXISTS ALONGSIDE A SYSTEMD TIMER, which is the first question a
reviewer should ask. Airflow is the resume artifact; the systemd timer is what
actually has to fire.

The cfdb Airflow runs in Docker Compose on a laptop that sleeps, and
`infra/tunnel.sh` refuses to run anywhere but a workstation -- so both the
scheduler and the database connection here are best-effort by construction. For
college football data a missed run costs a stale line. Here, the run that does
not fire is the morning the A/C is dead. So the production path is a timer on
`ecowitt-db`, and this is the development loop and the demonstration.

THE ONE PROPERTY THAT MUST HOLD: this calls the SAME entry point the timer
calls. `reporting.daily.main` is the whole task body -- there is no second
implementation of the report here, and nothing in the report knows which
scheduler invoked it. If that ever stops being true, this DAG stops being a
demonstration of the production path and becomes a fork of it.

    airflow dags trigger lakehouse_daily
"""

from datetime import datetime

from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator

# The same failure alerting the cfdb DAGs use. A report DAG that fails silently
# would be the exact failure mode this whole project is built against, and
# `on_failure_callback` in default_args is what makes that impossible to forget
# on a new task.
try:
    from src.alerting import failure_callback
except ImportError:  # pragma: no cover
    # This repo's DAG folder may be mounted without cfdb's src/ alongside it.
    # A missing alerting import must not take the DAG out of service -- the
    # email is the point, and a DAG that fails to parse sends nothing.
    failure_callback = None


def send_daily_email(**context):
    """Run the report exactly as the timer does.

    `--test` rather than `--send`: this scheduler is a laptop that sleeps, and a
    production email that arrives at 11am because the lid was shut until then is
    worse than no email, because it teaches three people that the timing means
    nothing. The VM timer owns production; this proves the path end to end
    against the real database, to Marc only.

    Raising on a non-zero exit is deliberate -- `main` returns 1 when a send
    fails, and a task that swallowed that would be green on the morning the
    email did not go out.
    """
    from reporting.daily import main

    code = main(["--test"])
    if code != 0:
        raise RuntimeError(
            f"reporting.daily exited {code} — the daily email did not go out. "
            "The task log carries the reason; `diagnose()` names the fix for an "
            "SMTP failure."
        )
    return code


default_args = {"owner": "ecowitt", "retries": 0}
if failure_callback is not None:
    default_args["on_failure_callback"] = failure_callback

with DAG(
    dag_id="lakehouse_daily",
    description="Daily lakehouse email — is the house all right?",
    default_args=default_args,
    start_date=datetime(2026, 8, 28),
    # 12:00 UTC = 07:00 America/Chicago in summer. The VM timer states its zone
    # explicitly and is the one that matters; this is the dev loop.
    schedule="0 12 * * *",
    # Never backfill. Each run reports on yesterday, so a catch-up would send a
    # week of stale emails at once — and §5.3 refuses backfilled production
    # sends for exactly that reason.
    catchup=False,
    max_active_runs=1,
    tags=["ecowitt", "lakehouse", "reporting"],
) as dag:
    PythonOperator(task_id="send_daily_email", python_callable=send_daily_email)
