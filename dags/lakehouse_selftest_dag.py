"""Airflow DAG: prove a lakehouse ACTION email can still be delivered.

Ported from cfdb's `alerting_selftest_dag.py`, which fails on purpose to prove
alerts still arrive. The gap is the same one: `lakehouse_daily` running green
proves the report builds, and proves nothing about whether an ACTION email --
the one that only ever gets sent on a bad morning, and therefore the one least
exercised -- can still be rendered and delivered.

Manual trigger only. It reaches the TEST address and needs no database, so it
still answers the question when the database is the thing that is broken.

    airflow dags trigger lakehouse_selftest

Expect: a subject beginning `[lakehouse] SELFTEST ACTION`, a line in the local
JSONL log, and nothing at all reaching the production list.
"""

from datetime import datetime

from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator

try:
    from src.alerting import failure_callback
except ImportError:  # pragma: no cover
    failure_callback = None


def send_synthetic_action_email(**context):
    from reporting.daily import main

    code = main(["--selftest", "--test"])
    if code != 0:
        raise RuntimeError(
            "the synthetic ACTION email did not go out. Real ones would not "
            "either — the task log carries the SMTP diagnosis."
        )
    return code


default_args = {"owner": "ecowitt", "retries": 0}
if failure_callback is not None:
    default_args["on_failure_callback"] = failure_callback

with DAG(
    dag_id="lakehouse_selftest",
    description="Sends a synthetic ACTION email to the test address",
    default_args=default_args,
    start_date=datetime(2026, 8, 28),
    schedule=None,
    catchup=False,
    tags=["ecowitt", "lakehouse", "diagnostic"],
) as dag:
    PythonOperator(
        task_id="send_synthetic_action_email", python_callable=send_synthetic_action_email
    )
