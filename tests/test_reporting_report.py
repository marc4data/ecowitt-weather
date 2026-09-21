"""Phase A: the report builds correctly from fixture frames.

Five days, each chosen because it breaks something a naive implementation gets
wrong: a clean day, a day with no data at all, a house that is already hot
(rather than heating up), a failing cell, and a 25-hour Sunday in November.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import ecowitt_daily as daily
import ecowitt_nb as nb
import pandas as pd
import pytest
from conftest import TZ, build_day, day_bounds, seed_observations, seed_runs

from reporting import report as report_mod


def make_inputs(conn, day_str, frame, *, for_date=None, runs=24):
    """Assemble Inputs the way `gather` would, without a Postgres to gather from.

    `runs=0` describes a window no ingestion run covered -- which is what 1
    August 2026 actually looks like, and what the contact-list gate turns on.
    """
    start, end = day_bounds(day_str)
    if runs:
        seed_runs(conn, start, end, n=runs)
    seed_observations(conn, frame)
    meta = nb.load_meta(conn)

    checks = (
        daily.run_checks(conn, frame, meta, start, end)
        if frame.notna().any().any()
        else pd.DataFrame(columns=["check", "verdict", "measured", "note"])
    )
    pivot = (
        pd.DataFrame({f"{start:%a %d}": checks.set_index("check").verdict})
        if not checks.empty
        else pd.DataFrame()
    )

    indoor = frame.get("indoor.temperature")
    extremes = (
        pd.DataFrame(
            [
                {
                    "day": for_date or start.date(),
                    "outdoor_high": frame["outdoor.temperature"].max() if not frame.empty else None,
                    "outdoor_low": frame["outdoor.temperature"].min() if not frame.empty else None,
                    "indoor_high": indoor.max() if indoor is not None else None,
                    "indoor_low": indoor.min() if indoor is not None else None,
                }
            ]
        )
        if frame.notna().any().any()
        else pd.DataFrame()
    )

    batteries = (
        pd.DataFrame(
            [
                {
                    "metric": m,
                    "value_num": float(frame[m].dropna().iloc[-1]),
                    "ts_utc": end,
                    "last_changed": end - timedelta(days=2),
                }
                for m in frame.columns
                if m.startswith("battery.") and frame[m].notna().any()
            ]
        )
        if frame.notna().any().any()
        else pd.DataFrame(columns=["metric", "value_num", "ts_utc", "last_changed"])
    )

    return report_mod.Inputs(
        for_date=for_date or start.date(),
        start=start,
        end=end,
        meta=meta,
        day=frame,
        week=frame,
        month=frame,
        checks=checks,
        pivot=pivot,
        measured=(checks.set_index("check").measured if not checks.empty else pd.Series(dtype=str)),
        notes=(checks.set_index("check").note if not checks.empty else pd.Series(dtype=str)),
        extremes=extremes,
        batteries=batteries,
    )


def build(conn, day_str, frame, **kwargs):
    generated = datetime.now(TZ)
    return report_mod.build(
        make_inputs(conn, day_str, frame, **kwargs), generated_at=generated, mode="dry-run"
    )


# --------------------------------------------------------------------------


def test_clean_day_is_ok_and_says_so(fixture_db):
    start, end = day_bounds("2026-08-05")
    frame = build_day(start, end)
    report = build(fixture_db, "2026-08-05", frame)

    assert report.severity == "ok"
    assert report.has_data
    assert "All systems go" in report.one_line
    assert (report.checks.verdict == "FAIL").sum() == 0
    # The twelve numbers, each with the time it happened -- timing is half the
    # story, and a headline table without it is a different thing.
    assert not report.headlines.empty
    assert set(report.headlines.columns) == {"measure", "value", "when"}


def test_no_data_day_is_an_alert_not_a_quiet_report(fixture_db):
    """§8.2. If the pipeline died the email must say so. Silence is never the report."""
    start, end = day_bounds("2026-08-06")
    frame = build_day(start, end, empty=True)
    report = build(fixture_db, "2026-08-06", frame)

    assert report.severity == "alert"
    assert not report.has_data
    assert "station or the pipeline is down" in report.one_line
    assert report.headlines.empty


def test_house_already_hot_fails_even_though_it_is_not_climbing(fixture_db):
    """§4, the gap the whole project exists to close.

    Flat at 95 ºF produces no run of rising hourly means, so `indoor climate
    holding` passes -- correctly. The protection band must fail anyway.
    """
    start, end = day_bounds("2026-08-16")
    frame = build_day(start, end, indoor=95.0, indoor_room=93.0)
    report = build(fixture_db, "2026-08-16", frame)

    verdicts = report.checks.set_index("check").verdict
    assert verdicts["indoor climate holding"] == "PASS", "flat is not a climb"
    assert verdicts["indoor within protection band"] == "FAIL"
    assert report.severity == "alert"
    # A room has to corroborate before heat is called a failure.
    measured = report.checks.set_index("check").measured["indoor within protection band"]
    assert "rooms agreeing" in measured


def test_one_hot_room_alone_is_a_warning_not_a_failure(fixture_db):
    """A single room baking in afternoon sun is not the house.

    The console is authoritative; without corroboration this is a WARN. Only the
    console is pushed over the ceiling here, and the room is left cool.
    """
    start, end = day_bounds("2026-08-17")
    frame = build_day(start, end, indoor=90.0, indoor_room=74.0)
    report = build(fixture_db, "2026-08-17", frame)

    verdicts = report.checks.set_index("check").verdict
    assert verdicts["indoor within protection band"] == "WARN"
    assert report.severity == "warn"


def test_three_scattered_hot_hours_do_not_trigger_it(fixture_db):
    """Persistence is consecutive hours, not a daily count.

    Three scattered hot hours is weather leaking in when a door opens; three in
    a row is a system.
    """
    start, end = day_bounds("2026-08-18")
    scattered = {3, 11, 19}
    frame = build_day(
        start,
        end,
        indoor=lambda h: 95.0 if int(h) in scattered else 74.0,
        indoor_room=lambda h: 94.0 if int(h) in scattered else 73.0,
    )
    report = build(fixture_db, "2026-08-18", frame)

    assert report.checks.set_index("check").verdict["indoor within protection band"] == "PASS"


def test_cold_house_fails_without_needing_a_room_to_agree(fixture_db):
    """Corroboration is required on the hot side only.

    A single room near an exterior wall running cold in January is an early
    sign, and the cost of being wrong is a burst pipe rather than a phone call.
    """
    start, end = day_bounds("2026-08-19")
    frame = build_day(start, end, indoor=40.0, indoor_room=70.0)
    report = build(fixture_db, "2026-08-19", frame)

    checks = report.checks.set_index("check")
    assert checks.verdict["indoor within protection band"] == "FAIL"
    assert "below 45" in checks.measured["indoor within protection band"]


def test_low_battery_fails_and_says_the_threshold_is_derived(fixture_db):
    """§7.3. The AA floors are not an Ecowitt specification and must not read as one."""
    start, end = day_bounds("2026-08-20")
    frame = build_day(start, end, battery_ch1=1.15)
    report = build(fixture_db, "2026-08-20", frame)

    checks = report.checks.set_index("check")
    assert checks.verdict["battery levels"] == "FAIL"
    assert "DERIVED" in checks.note["battery levels"]
    assert "0.1 V steps" in checks.note["battery levels"]


def test_battery_warn_band(fixture_db):
    start, end = day_bounds("2026-08-20")
    frame = build_day(start, end, battery_ch1=1.40)
    report = build(fixture_db, "2026-08-20", frame)
    assert report.checks.set_index("check").verdict["battery levels"] == "WARN"


def test_dst_day_is_judged_against_its_real_length(fixture_db):
    """§8.8. 1 November 2026 is 25 hours in America/Chicago.

    A day counted as 288 slots would report 300/288 = 104% coverage, which is
    both absurd and, worse, would hide a real gap on the one day of the year the
    arithmetic is different.
    """
    start, end = day_bounds("2026-11-01")
    # Absolute, not wall-clock: two aware datetimes sharing a tzinfo subtract by
    # wall clock and would report a flat 24 h. That difference is the bug this
    # test exists to hold down.
    assert (end.astimezone(timezone.utc) - start.astimezone(timezone.utc)) == timedelta(hours=25)

    frame = build_day(start, end)
    assert len(frame) == 300

    report = build(fixture_db, "2026-11-01", frame)
    measured = report.checks.set_index("check").measured["grid coverage"]
    assert "300/300" in measured
    assert "100.0%" in measured


def test_spring_forward_day_is_23_hours(fixture_db):
    start, end = day_bounds("2026-03-08")
    assert (end.astimezone(timezone.utc) - start.astimezone(timezone.utc)) == timedelta(hours=23)
    assert len(build_day(start, end)) == 276


def test_replay_is_decided_by_the_date_not_the_flag(fixture_db):
    """§5.4. A replay cannot lose its banner by being sent through another path."""
    start, end = day_bounds("2026-08-05")
    frame = build_day(start, end)
    old = build(fixture_db, "2026-08-05", frame)
    assert old.is_replay

    fresh = build(fixture_db, "2026-08-05", frame, for_date=report_mod.yesterday())
    assert not fresh.is_replay


def test_the_house_leads_when_several_checks_fail(fixture_db):
    """21 August 2026 failed on both the house and a rain accumulator.

    Without an explicit order the subject line led with the rain quirk while the
    house sat at 93 ºF.
    """
    start, end = day_bounds("2026-08-21")
    frame = build_day(start, end, indoor=95.0, indoor_room=94.0)
    # A rain accumulator that falls without resetting to zero.
    frame.loc[frame.index[100], "rainfall_piezo.daily"] = 0.5
    frame.loc[frame.index[101], "rainfall_piezo.daily"] = 0.2

    report = build(fixture_db, "2026-08-21", frame)
    failing = [item["check"] for item in report.attention["items"] if item["verdict"] == "FAIL"]
    assert failing[0] == "indoor within protection band"
    assert "rain accumulators only reset to zero" in failing


# --- R-002: a rolling window is not a resetting accumulator ----------------
#
# Both series below are REAL, read off the production database on 2026-09-21 and
# recorded here. The fixture harness builds synthetic weather, but these two
# numbers are the whole point of the round, so inventing them would test the
# test rather than the check.

# rainfall_piezo.1_hour, 2026-09-12 14:50..16:00 local. A trailing 60-minute
# total decaying as rain ages out of the window -- the behaviour that put
# "6 irregular" in front of three people.
SEP12_1_HOUR_DECAY = [0.09, 0.09, 0.09, 0.09, 0.09, 0.08, 0.06, 0.05,
                      0.05, 0.04, 0.02, 0.01, 0.01, 0.01, 0.0]

# 2026-08-21 06:30..06:45 local, the console re-zero. daily and weekly each
# lose a cent-inch and land ABOVE zero, which rain cannot do.
AUG21_DAILY = [0.06, 0.06, 0.07, 0.06]
AUG21_WEEKLY = [0.09, 0.09, 0.10, 0.09]


def _put(frame, metric, first_stamp, values):
    """Write a recorded series into the fixture frame at a wall-clock time."""
    h, m = (int(x) for x in first_stamp.split(":"))
    start = frame.index[0].normalize() + pd.Timedelta(hours=h, minutes=m)
    for i, v in enumerate(values):
        frame.loc[start + pd.Timedelta(minutes=5 * i), metric] = v
    return frame


def test_a_rolling_hourly_total_decaying_is_not_an_irregular_reset(fixture_db):
    """12 Sep 2026: `1_hour` steps 0.08 -> 0.06 -> 0.05 as rain ages out.

    Catalogued `accumulator`, so before R-002 every one of those steps counted
    as a rain total going backwards. It is a trailing window; decaying is what
    it is for.
    """
    start, end = day_bounds("2026-09-12")
    frame = _put(build_day(start, end), "rainfall_piezo.1_hour", "14:50", SEP12_1_HOUR_DECAY)

    report = build(fixture_db, "2026-09-12", frame)
    row = report.checks[report.checks.check == "rain accumulators only reset to zero"].iloc[0]
    assert row.verdict == "PASS", (
        f"a rolling window decayed and the check called it irregular: {row.note}"
    )


def test_a_real_backwards_step_in_a_true_accumulator_still_fails(fixture_db):
    """21 Aug 2026: `daily` 0.07 -> 0.06 and `weekly` 0.10 -> 0.09 in one slot.

    The exemption must not reach these. They are the only genuine backwards
    step in the record, and the check earns its keep once in 51 days on them.
    The COUNT is asserted, not just the verdict: an exemption widened to cover
    `daily` would still leave `weekly` failing, and a bare `verdict == FAIL`
    would sail straight through that.
    """
    start, end = day_bounds("2026-08-21")
    frame = build_day(start, end)
    _put(frame, "rainfall_piezo.daily", "06:30", AUG21_DAILY)
    _put(frame, "rainfall_piezo.weekly", "06:30", AUG21_WEEKLY)

    report = build(fixture_db, "2026-08-21", frame)
    row = report.checks[report.checks.check == "rain accumulators only reset to zero"].iloc[0]
    assert row.verdict == "FAIL"
    assert row.measured == "2 irregular", f"expected both metrics flagged, got {row.measured!r}"
    assert "rainfall_piezo.daily" in row.note
    assert "rainfall_piezo.weekly" in row.note


def test_the_exemption_names_its_metric_rather_than_matching_a_pattern(fixture_db):
    """`daily`, `weekly`, `monthly`, `yearly` are all period names too.

    A prefix/suffix rule over `rainfall_piezo.*` would swallow the one case
    this check exists to catch, so the set is pinned to exactly one member.
    """
    assert set(daily.ROLLING_NOT_ACCUMULATING) == {"rainfall_piezo.1_hour"}


def test_action_email_says_so_when_no_contact_is_configured(fixture_db):
    """§11.5 is open, and a missing instruction has to look missing."""
    start, end = day_bounds("2026-08-16")
    report = build(fixture_db, "2026-08-16", build_day(start, end, indoor=95.0, indoor_room=93.0))
    assert any("No contact is configured" in line for line in report.actions)


@pytest.mark.parametrize("hours,expected", [(0, 0), (1, 1), (5, 5)])
def test_hourly_runs_counts_consecutive_hours(hours, expected):
    index = pd.date_range("2026-08-01", periods=24, freq="1h")
    values = [95.0 if i < hours else 70.0 for i in range(24)]
    run, start, _ = daily.hourly_runs(pd.Series(values, index=index), 85.0)
    assert run == expected
    assert (start is None) == (expected == 0)
