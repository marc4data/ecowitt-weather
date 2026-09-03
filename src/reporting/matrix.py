"""Every check, every day since the pipeline was turned on, as one grid.

    python -m reporting.matrix                  # the whole record
    python -m reporting.matrix --days 14        # just the last fortnight
    python -m reporting.matrix --out report.html

A daily email answers "is the house all right this morning". This answers a
different question that no single email can: **which checks actually fire, and
how often.** That is what tells you whether a check is earning its place or
training three people to skim — the argument that got `no flatlined sensor`
removed on 2026-08-28, after the grid showed it warning on 4 of 27 days and
being right on none of them.

Reads the same `run_checks` the email and the notebook read. It cannot disagree
with them, because there is nothing here to disagree with.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from . import config, data
from .report import day_bounds
from .shared import daily, nb

# The email's own tints, so a verdict looks the same wherever it is read. Light
# enough to survive a greyscale printer, which is where this is likely to end up.
FILL = {
    "PASS": ("#e2f0ec", "#123a33"),
    "WARN": ("#f9efd8", "#4a3210"),
    "FAIL": ("#f7e4de", "#5e2716"),
    "": ("#f4f4f1", "#9a9a9a"),
}


def build_matrix(conn, *, days: int, end: date | None = None):
    """checks x days -> verdict. One pass over the window, not one per day."""
    zone = ZoneInfo(config.DISPLAY_ZONE)
    last = end or (datetime.now(zone).date() - timedelta(days=1))
    _, window_end = day_bounds(last)
    meta = nb.load_meta(conn)

    pivot, _, notes = daily.rolling_checks(conn, meta, nb.fetch_window, window_end, days=days)
    return pivot, notes


def to_html(pivot: pd.DataFrame, notes: pd.Series, *, generated: datetime) -> str:
    """The grid, plus what each row actually counted."""
    if pivot.empty:
        return "<p>No days with data in the window.</p>"

    totals = {verdict: int((pivot == verdict).sum().sum()) for verdict in ("PASS", "WARN", "FAIL")}
    days = pivot.shape[1]
    clean_days = int((pivot != "FAIL").all().sum())
    perfect_days = int(((pivot == "PASS") | (pivot == "")).all().sum())

    head = "".join(
        f'<th style="padding:4px 3px;font-size:10px;font-weight:600;color:#6b6b6b;'
        f'writing-mode:vertical-rl;transform:rotate(180deg);white-space:nowrap;">'
        f"{escape(str(col))}</th>"
        for col in pivot.columns
    )

    rows = []
    for check in pivot.index:
        cells = []
        for col in pivot.columns:
            verdict = str(pivot.loc[check, col] or "")
            background, ink = FILL.get(verdict, FILL[""])
            cells.append(
                f'<td title="{escape(verdict or "no data")}" '
                f'style="background:{background};color:{ink};text-align:center;'
                f'font-size:9px;font-weight:700;padding:5px 2px;border:1px solid #fff;">'
                f"{verdict[:1] if verdict else '·'}</td>"
            )
        # How often this row is anything other than PASS -- the number that says
        # whether a check is informative or merely loud.
        row = pivot.loc[check]
        noise = int(((row == "WARN") | (row == "FAIL")).sum())
        share = 100.0 * noise / days if days else 0.0
        rows.append(
            f'<tr><th style="text-align:left;font-weight:500;font-size:12px;'
            f'padding:4px 10px 4px 0;white-space:nowrap;" '
            f'title="{escape(str(notes.get(check, "")))}">{escape(str(check))}</th>'
            + "".join(cells)
            + f'<td style="padding:4px 0 4px 10px;font-size:11px;color:#6b6b6b;'
            f'white-space:nowrap;">{noise}/{days} ({share:.0f}%)</td></tr>'
        )

    return f"""
<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;
            color:#1b1b1b;max-width:1100px;margin:0 auto;padding:24px;">
  <h1 style="font-size:20px;margin:0 0 4px 0;">Check results by day</h1>
  <p style="color:#6b6b6b;font-size:13px;margin:0 0 18px 0;">
    {escape(str(pivot.columns[0]))} to {escape(str(pivot.columns[-1]))} ·
    {days} days · generated {generated:%d %B %Y}
  </p>
  <p style="font-size:13px;margin:0 0 18px 0;">
    <strong>{perfect_days}</strong> of {days} days were completely clean ·
    <strong>{clean_days}</strong> had no failures ·
    {totals["FAIL"]} FAIL, {totals["WARN"]} WARN, {totals["PASS"]} PASS in all.
    The right-hand column is how often each check was not PASS — a check that is
    loud most days is not telling anybody anything.
  </p>
  <table cellspacing="0" cellpadding="0" style="border-collapse:collapse;">
    <tr><th></th>{head}
        <th style="font-size:10px;color:#6b6b6b;padding-left:10px;">not PASS</th></tr>
    {"".join(rows)}
  </table>
  <p style="color:#6b6b6b;font-size:11px;margin-top:16px;">
    P = pass · W = warning · F = failure · · = no data.
    Hover a check name for why it exists.
  </p>
</div>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m reporting.matrix",
        description="Every check against every day, as one grid.",
    )
    parser.add_argument(
        "--days", type=int, default=0, help="how many days back (default: the whole record)"
    )
    parser.add_argument("--out", default="data/reports/check_matrix.html")
    args = parser.parse_args(argv)

    zone = ZoneInfo(config.DISPLAY_ZONE)
    yesterday = datetime.now(zone).date() - timedelta(days=1)
    days = args.days or (yesterday - config.HISTORY_START).days + 1

    conn = data.connect_read()
    pivot, notes = build_matrix(conn, days=days, end=yesterday)

    generated = datetime.now(zone)
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(to_html(pivot, notes, generated=generated), encoding="utf-8")

    # The same grid on the terminal, because the answer is often one glance.
    print(pivot.to_string())
    print(f"\nwrote {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
