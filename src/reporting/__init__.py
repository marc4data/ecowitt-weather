"""The daily lakehouse email.

Answers one question for three people: is the house all right?

    reporting.report    what the email says      (pure; a database read, then no interpretation)
    reporting.render    how it says it           (pure; subject, text, HTML, images)
    reporting.charts    the three inline PNGs
    reporting.send      delivery, and the record that it happened
    reporting.daily     the entry point both the Airflow DAG and the systemd timer call

Detection lives in `notebooks/ecowitt_daily.py`, not here. That module already
carried `attention()` with the docstring "What a daily email keys off"; putting
a second copy of the thresholds in this package would be the exact failure this
project keeps designing against.
"""
