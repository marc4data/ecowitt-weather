"""Build the daily report: everything the email says, before anything renders it.

Split in two on purpose.

  `gather(conn, for_date)`   touches the database and nothing else
  `build(inputs, ...)`       is pure, so the exact content of tomorrow's email
                             can be produced from fixture frames in a test with
                             no database, no scheduler and no network

Nothing here decides how anything looks, and nothing here sends. Reading order
is fixed and is not cosmetic: the verdict comes first, because every number
under it is only as good as the checks that produced it -- the same argument
`explore_daily.ipynb` makes for putting boundary conditions before the summary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import text

from . import config
from .shared import daily, nb

# How far back the trend runs. Seven days is what makes "has this been drifting"
# answerable: a single day says whether today is broken, the row of days says
# whether the same check has been amber all week.
ROLLING_DAYS = 7

# Bucket widths for the two context frames.
#
# ⚠️ THE WEEK IS AT NATIVE RESOLUTION, and that is not an efficiency question.
# At hourly buckets the 7-day chart plotted MEANS, so 5 August's peak drew and
# labelled as 104 ºF while the summary table -- built from the 5-minute data --
# said 105.3 ºF. Both were right and they contradicted each other in the same
# email: the 3 pm hour ran 103.0 to 105.3 and averaged 103.8. A reader cannot
# be expected to know which number is the aggregate.
#
# So the week is fetched on the station's own 5-minute grid, and anything that
# wants coarser buckets (the rain chart) resamples locally, where the choice of
# rule is visible next to the chart that depends on it.
WEEK_BUCKET = ("5 minutes", "5min")
# The month is only used for the battery trace, which moves in 0.01 V steps
# over weeks. Hourly is plenty, and 30 days at 5 minutes would be 8,640 points
# per metric to draw a line that barely changes.
MONTH_BUCKET = ("1 hour", "1h")


@dataclass(frozen=True)
class Inputs:
    """Everything read from the database, for one report."""

    for_date: date
    start: datetime
    end: datetime
    meta: dict
    day: pd.DataFrame
    week: pd.DataFrame
    month: pd.DataFrame
    checks: pd.DataFrame
    pivot: pd.DataFrame
    measured: pd.Series
    notes: pd.Series
    extremes: pd.DataFrame  # one row per day: outdoor/indoor high and low
    batteries: pd.DataFrame  # latest voltage per battery metric, and its age


@dataclass(frozen=True)
class Report:
    """What the email says. Rendering turns this into words; it adds nothing."""

    for_date: date
    generated_at: datetime
    mode: str  # dry-run | test | production
    is_replay: bool
    zone: str

    severity: str  # ok | warn | alert
    headline: str
    one_line: str
    has_data: bool

    checks: pd.DataFrame
    attention: dict
    headlines: pd.DataFrame
    comparison: str
    house: dict
    equipment: list[dict]
    actions: list[str]

    # Frames the charts are drawn from. Held rather than drawn, so `build` stays
    # pure and a test can assert on content without rendering a PNG.
    day: pd.DataFrame = field(repr=False, default_factory=pd.DataFrame)
    week: pd.DataFrame = field(repr=False, default_factory=pd.DataFrame)
    month: pd.DataFrame = field(repr=False, default_factory=pd.DataFrame)
    meta: dict = field(repr=False, default_factory=dict)
    pivot: pd.DataFrame = field(repr=False, default_factory=pd.DataFrame)
    # True daily highs and lows, straight from the 5-minute data rather than
    # from a bucketed chart frame -- an hourly mean understates a peak, and the
    # four-week chart is a comparison of peaks.
    extremes: pd.DataFrame = field(repr=False, default_factory=pd.DataFrame)

    # A synthetic report, produced by `--selftest` to prove the path works. A
    # field on the report rather than a flag in the send path, so its label is
    # impossible to send without -- the same reasoning as the replay banner.
    is_selftest: bool = False

    # Claude's plain-English rewrite of the top of an ACTION email, when it ran.
    # None is the normal case and costs the email nothing (§6.3): the checks
    # already say what happened, in the words they were written to say it in.
    summary: dict | None = None


# --------------------------------------------------------------------------
# Bounds
# --------------------------------------------------------------------------


def day_bounds(for_date: date, tz: str = config.DISPLAY_ZONE):
    """The local calendar day, as an aware (start, end) pair.

    Built from two midnights rather than start + 24h. On a DST changeover those
    differ by an hour, and it is the calendar day that people mean -- so this
    yields a genuine 23- or 25-hour span, which `run_checks` then judges against
    its real length rather than an assumed 288 slots (§8.8).
    """
    zone = ZoneInfo(tz)
    start = datetime.combine(for_date, time.min, tzinfo=zone)
    end = datetime.combine(for_date + timedelta(days=1), time.min, tzinfo=zone)
    return start, end


def yesterday(tz: str = config.DISPLAY_ZONE) -> date:
    return (datetime.now(ZoneInfo(tz)) - timedelta(days=1)).date()


# --------------------------------------------------------------------------
# Gather -- the only part that touches the database
# --------------------------------------------------------------------------

_EXTREMES_SQL = """
SELECT (ts_utc AT TIME ZONE :zone)::date AS day,
       max(value_num) FILTER (WHERE metric = 'outdoor.temperature') AS outdoor_high,
       min(value_num) FILTER (WHERE metric = 'outdoor.temperature') AS outdoor_low,
       max(value_num) FILTER (WHERE metric = 'indoor.temperature')  AS indoor_high,
       min(value_num) FILTER (WHERE metric = 'indoor.temperature')  AS indoor_low
  FROM observation
 WHERE ts_utc >= :start AND ts_utc < :end
   AND metric IN ('outdoor.temperature', 'indoor.temperature')
 GROUP BY 1 ORDER BY 1
"""

# The latest reading per battery metric, and when it last actually moved.
#
# A battery flat for 30 days and a battery that has stopped updating look
# identical, and `no flatlined sensor` cannot see the difference -- it only
# examines instantaneous/derived/extremum metrics, and every battery metric is
# kind='diagnostic'. This is not an alarm (a fresh alkaline AA legitimately
# holds a step for weeks); it is so the digest can say "unchanged for 30 days"
# rather than implying it was measured this morning.
_BATTERY_SQL = """
WITH latest AS (
    SELECT DISTINCT ON (metric) metric, value_num, ts_utc
      FROM observation
     WHERE metric LIKE 'battery.%' AND ts_utc < :end AND value_num IS NOT NULL
     ORDER BY metric, ts_utc DESC
)
SELECT l.metric, l.value_num, l.ts_utc,
       (SELECT max(o.ts_utc) FROM observation o
         WHERE o.metric = l.metric AND o.ts_utc < :end
           AND o.value_num IS DISTINCT FROM l.value_num) AS last_changed
  FROM latest l ORDER BY l.metric
"""


def gather(conn, for_date: date, *, rolling_days: int = ROLLING_DAYS) -> Inputs:
    """Read everything the report needs. One pass, no interpretation."""
    start, end = day_bounds(for_date)
    meta = nb.load_meta(conn)

    day = nb.fetch_window(conn, start, end, bucket="5 minutes", freq="5min")
    week = nb.fetch_window(
        conn, end - timedelta(days=7), end, bucket=WEEK_BUCKET[0], freq=WEEK_BUCKET[1]
    )
    month = nb.fetch_window(
        conn, end - timedelta(days=30), end, bucket=MONTH_BUCKET[0], freq=MONTH_BUCKET[1]
    )

    # The reported day is checked on its own rather than being read out of the
    # rolling pivot. `rolling_checks` skips days with no data, so on a dead-
    # pipeline morning the pivot's newest column is some earlier, healthy day --
    # and reporting that as today would be the exact failure §8.2 forbids.
    checks = (
        daily.run_checks(conn, day, meta, start, end)
        if day.notna().any().any()
        else pd.DataFrame(columns=["check", "verdict", "measured", "note"])
    )

    pivot, measured, notes = daily.rolling_checks(
        conn, meta, nb.fetch_window, end, days=rolling_days
    )

    extremes = pd.read_sql(
        text(_EXTREMES_SQL),
        conn,
        params={"zone": config.DISPLAY_ZONE, "start": end - timedelta(days=30), "end": end},
    )
    batteries = pd.read_sql(text(_BATTERY_SQL), conn, params={"end": end})

    return Inputs(
        for_date=for_date,
        start=start,
        end=end,
        meta=meta,
        day=day,
        week=week,
        month=month,
        checks=checks,
        pivot=pivot,
        measured=measured,
        notes=notes,
        extremes=extremes,
        batteries=batteries,
    )


# --------------------------------------------------------------------------
# Build -- pure
# --------------------------------------------------------------------------


def _severity(inputs: Inputs) -> tuple[str, str, dict]:
    """Severity, headline, and the attention payload behind them.

    A day with no data is an ALERT, not a quiet report. If the pipeline died,
    coverage is 0% and the email must go out saying plainly that the station or
    the pipeline is down. Silence is never the report (§8.2).
    """
    if inputs.checks.empty:
        payload = {
            "severity": "alert",
            "headline": "no data for the window",
            "items": [],
            "resolved_earlier": [],
            "window_days": 0,
        }
        return "alert", "no data — the station or the pipeline is down", payload

    payload = daily.attention(inputs.pivot, inputs.measured, inputs.notes)

    # `attention` reads the newest column of the pivot. That is the reported day
    # only when the reported day made it into the pivot at all, which is checked
    # above -- so the verdicts are re-derived from this day's own checks and the
    # pivot is used only for the trend and the run length.
    today = inputs.checks.set_index("check")
    # Ordered by consequence, not by the order the checks happen to run in: the
    # house leads, then whether we can still see the house, then whether the
    # data is fit to answer either question.
    fails = sorted(today.index[today.verdict == "FAIL"], key=config.priority)
    warns = sorted(today.index[today.verdict == "WARN"], key=config.priority)
    severity = "alert" if fails else ("warn" if warns else "ok")

    # An incident cannot be older than the record it is measured in. Without
    # this bound, replaying 1 August 2026 -- the first day there is any data at
    # all -- reported "day 7+ of this", because the six days before it are
    # empty and an empty day fails every coverage check. That is commissioning
    # being read as a week-old failure, the distinction CLAUDE.md §4 draws.
    record_days = (inputs.for_date - config.HISTORY_START).days + 1

    def entry(name: str) -> dict:
        row = today.loc[name]
        prior = [item for item in payload.get("items", []) if item["check"] == name]
        return {
            "check": name,
            "verdict": row.verdict,
            "measured": row.measured,
            "note": row.note,
            "days": min(prior[0]["days"] if prior else 1, max(record_days, 1)),
            "action": config.GENERIC_ACTIONS.get(name),
        }

    items = [entry(name) for name in fails + warns]
    payload = dict(payload, severity=severity, items=items)

    # `items` is already ordered by consequence, so the first one is the one the
    # subject line should carry.
    headline = _headline_for(items[0]) if items else "all checks passed"
    return severity, headline, payload


def _headline_for(item: dict) -> str:
    """One clause, specific enough that the subject alone is often enough.

    The check's own `measured` field is already an English fragment -- that is
    what it was written for -- so the headline is the check name plus its
    measurement rather than a second, parallel description that could drift.
    """
    measured = str(item.get("measured") or "").split(" · ")[0].strip()
    # `measured` is written to be read, so it is used verbatim rather than
    # paraphrased into a second description that could drift from the check.
    # Trimmed only because a subject line is truncated by the client, and a
    # truncated subject keeps its beginning.
    if len(measured) > 58:
        measured = measured[:57].rstrip(" ,—-") + "…"
    return f"{item['check']} — {measured}" if measured else item["check"]


def _one_line(inputs: Inputs, severity: str, items: list[dict], house: dict) -> str:
    """The first line: a sentence a non-technical reader can act on (§6.3.1).

    Not a headline and not a status code. "ACTION" tells Stacy something is
    wrong; "the lakehouse has been over 85 ºF since Thursday 13 August" tells her
    what. The named cases are the failures whose plain-English meaning is
    established -- everything else degrades to naming the check and its own
    measurement rather than guessing at what it implies.
    """
    if inputs.checks.empty:
        return (
            "No data arrived for this day at all. The station or the pipeline "
            "is down — nothing below describes the house."
        )

    high = inputs.day.get("outdoor.temperature")
    peak = f"{high.max():.0f} ºF" if high is not None and high.notna().any() else None
    if severity == "ok":
        return "All systems go." + (f" Yesterday topped out at {peak}." if peak else "")
    if severity == "warn":
        leading = items[0]["check"] if items else "something"
        return f"Working, with something worth a glance: {leading}."

    leading = items[0] if items else {}
    check = leading.get("check")

    if check == "indoor within protection band":
        since = house.get("breach_since")
        when = f"since {since:%A %d %B}" if since else "for most of the day"
        if house.get("high") is not None and house["high"] > house["ceiling"]:
            return (
                f"The lakehouse has been over {house['ceiling']:.0f} ºF {when}, "
                f"reaching {house['high']:.0f} ºF. The A/C does not appear to be "
                "running."
            )
        return (
            f"The lakehouse has been below {house['floor']:.0f} ºF {when}. "
            "Pipes are the concern, not comfort."
        )
    if check == "sensors reporting recently":
        return (
            "Part of the station has stopped reporting, so the numbers below "
            "do not describe the whole house."
        )
    if check == "grid coverage":
        return (
            "A large part of the day is missing from the record, so the numbers "
            "below are incomplete."
        )
    return f"Something needs a person: {check} — {leading.get('measured', '')}"


def _comparison(inputs: Inputs) -> str:
    """Where this day sat against the last 7 and 30 days. One sentence.

    Computed from true daily extremes read out of the 5-minute data, not from
    the bucketed chart frames: an hourly mean understates a peak, and a ranking
    built on understated peaks would be quietly wrong in both directions.
    """
    frame = inputs.extremes
    if frame.empty or "outdoor_high" not in frame:
        return ""
    frame = frame.dropna(subset=["outdoor_high"])
    if frame.empty:
        return ""
    today = frame[frame.day == inputs.for_date]
    if today.empty:
        return ""
    high = float(today.outdoor_high.iloc[0])

    history = frame[frame.day < inputs.for_date]
    parts = []
    if len(history) >= 3:
        warmer = int((history.outdoor_high >= high).sum())
        span = len(history)
        if warmer == 0:
            parts.append(f"the warmest of the last {span} days")
        elif warmer <= 2:
            parts.append(f"among the {warmer + 1} warmest of the last {span} days")
        else:
            parts.append(f"about average for the last {span} days ({warmer} of them were warmer)")

    indoor = today.indoor_high.iloc[0], today.indoor_low.iloc[0]
    if pd.notna(indoor[0]) and pd.notna(indoor[1]):
        parts.append(f"indoor held {indoor[1]:.0f}–{indoor[0]:.0f} ºF")
    return f"Outdoor high {high:.0f} ºF — " + ", ".join(parts) + "." if parts else ""


def _breach_since(inputs: Inputs) -> date | None:
    """The first day of the current run outside the band -- "since when" (§6.3.2).

    Walks back through the daily extremes already gathered, so it costs no extra
    query and can see far further than the 7-day trend: on 21 August 2026 the
    run length within the window is "7 or more", while this reports the actual
    onset, 13 August. "Since Thursday" is a fact somebody can act on; "recently"
    is not.

    Returns None when the run reaches the edge of the 30 days, because the
    beginning is then genuinely outside what was looked at.
    """
    frame = inputs.extremes
    if frame.empty or "indoor_high" not in frame:
        return None
    highs = frame.dropna(subset=["indoor_high"]).set_index("day").indoor_high
    if inputs.for_date not in highs.index or highs.loc[inputs.for_date] <= daily.PROTECT_MAX_F:
        return None
    days = [d for d in highs.index if d <= inputs.for_date]
    onset = None
    for day_key in reversed(days):
        if highs.loc[day_key] > daily.PROTECT_MAX_F:
            onset = day_key
        else:
            break
    return None if onset == days[0] else onset


def _house(inputs: Inputs) -> dict:
    """Indoor against the protection band -- a position, not just a number."""
    series = inputs.day.get("indoor.temperature")
    humidity = inputs.day.get("indoor.humidity")
    out = {
        "floor": daily.PROTECT_MIN_F,
        "ceiling": daily.PROTECT_MAX_F,
        "rh_ceiling": daily.PROTECT_RH_WARN,
        "low": None,
        "high": None,
        "last": None,
        "rh_high": None,
        "in_band": None,
        "breach_since": _breach_since(inputs),
    }
    if series is not None and series.notna().any():
        clean = series.dropna()
        out |= {
            "low": float(clean.min()),
            "high": float(clean.max()),
            "last": float(clean.iloc[-1]),
        }
        out["in_band"] = daily.PROTECT_MIN_F <= clean.max() <= daily.PROTECT_MAX_F
    if humidity is not None and humidity.notna().any():
        out["rh_high"] = float(humidity.dropna().max())
    return out


def _equipment(inputs: Inputs) -> list[dict]:
    """One entry per battery: level, verdict, and how long it has held that level."""
    rows = []
    for row in inputs.batteries.itertuples():
        limit = daily.BATTERY_LIMITS.get(row.metric)
        value = row.value_num
        verdict = "PASS"
        if limit is not None and value is not None:
            if limit["mode"] == "peak":
                # A peak threshold cannot be judged from one reading; the day's
                # own peak is what `battery levels` checks. Here the latest
                # value is reported as context, never as a verdict.
                verdict = "PASS"
            elif value <= limit["fail"]:
                verdict = "FAIL"
            elif value <= limit["warn"]:
                verdict = "WARN"
        held_days = None
        if row.last_changed is not None and pd.notna(row.last_changed):
            held_days = (inputs.end - row.last_changed).days
        rows.append(
            {
                "metric": row.metric,
                "label": row.metric.rsplit(".", 1)[-1],
                "value": None if value is None else float(value),
                "verdict": verdict,
                "held_days": held_days,
                "basis": (limit or {}).get("basis"),
                "sensor": (limit or {}).get("sensor"),
            }
        )
    return rows


def _actions(items: list[dict]) -> list[str]:
    """What to do, naming who -- §6.3 step 3.

    The names come from the environment, never from the repository: they are
    other people's phone numbers and, in one case, who knows where the key is.
    When none is configured this returns an explicit line saying so -- a missing
    instruction has to look missing, because an action email whose action
    section is quietly empty is a notification wearing the wrong subject line.
    """
    # Failing checks only. A warning's advice in the middle of an ACTION email
    # dilutes the thing that actually needs doing -- 21 August produced "check
    # the A/C breaker" followed by a note about the weekly gap sweep.
    failing = [item for item in items if item.get("verdict") == "FAIL"] or items
    out = [item["action"] for item in failing if item.get("action")]

    # The phone numbers appear ONLY when the failure is about the house. A data
    # failure -- a missed ingestion run, a gap in the grid -- needs Marc and a
    # look at the timers, not a neighbour driving to an empty house. Replaying
    # 1 August 2026 produced exactly that: its only failure was "no ingestion
    # run covered this window", and the email listed three people to call.
    names = [item["check"] for item in failing]
    if not config.needs_a_person(names):
        out.append(
            "Nothing here needs anybody to go to the house — these are data "
            "problems, not house problems. They are Marc's to look at."
        )
        return out

    if people := config.contacts():
        out += [
            " — ".join(part for part in (who, reach, what) if part) for who, reach, what in people
        ]
    else:
        out.append(
            f"No contact is configured for the house ({config.ENV_CONTACTS} is "
            "unset), so this email cannot say who should go. Tell Marc."
        )
    return out


def build(inputs: Inputs, *, generated_at: datetime, mode: str) -> Report:
    """Turn what was read into what the email says. Pure."""
    severity, headline, attention = _severity(inputs)
    house = _house(inputs)
    return Report(
        for_date=inputs.for_date,
        generated_at=generated_at,
        mode=mode,
        # Any day other than yesterday is a replay, whichever flag produced it.
        # Computed from the dates rather than from the mode, so a replay cannot
        # lose its banner by being sent through a different path (§5.4).
        is_replay=inputs.for_date != yesterday(),
        zone=config.DISPLAY_ZONE,
        severity=severity,
        headline=headline,
        one_line=_one_line(inputs, severity, attention.get("items", []), house),
        has_data=not inputs.checks.empty,
        checks=inputs.checks,
        attention=attention,
        headlines=(
            daily.headlines(inputs.day, inputs.meta)
            if inputs.day.notna().any().any()
            else pd.DataFrame()
        ),
        comparison=_comparison(inputs),
        house=house,
        equipment=_equipment(inputs),
        actions=_actions(attention.get("items", [])) if severity == "alert" else [],
        day=inputs.day,
        week=inputs.week,
        month=inputs.month,
        meta=inputs.meta,
        pivot=inputs.pivot,
        extremes=inputs.extremes,
    )


def build_report(
    conn, for_date: date, *, generated_at: datetime | None = None, mode: str = "dry-run"
) -> Report:
    """gather + build, for callers that have a connection and want the report."""
    generated_at = generated_at or datetime.now(ZoneInfo(config.DISPLAY_ZONE))
    return build(gather(conn, for_date), generated_at=generated_at, mode=mode)


def as_dict(report: Report) -> dict[str, Any]:
    """A JSON-safe summary, for the local log and for tests."""
    return {
        "for_date": report.for_date.isoformat(),
        "generated_at": report.generated_at.isoformat(),
        "mode": report.mode,
        "is_replay": report.is_replay,
        "severity": report.severity,
        "headline": report.headline,
        "has_data": report.has_data,
        "failing": [
            item["check"]
            for item in report.attention.get("items", [])
            if item.get("verdict") == "FAIL"
        ],
    }
