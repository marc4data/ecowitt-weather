"""Phase B: what the email actually says.

The property that matters most here is the one nobody notices until it fails:
**the text alternative has to stand alone.** Gmail defers images from unfamiliar
senders, and Stacy and Tad have never had mail from this address, so the first
few of these emails will arrive with every chart blocked. If the verdict, the
numbers, the action and the replay banner do not survive that, the email does
not work for the people it was written for.
"""

from __future__ import annotations

import pandas as pd
import pytest
from conftest import build_day, day_bounds
from test_reporting_report import build

from reporting import charts, config, render


def rendered(conn, day_str, frame, **kwargs):
    # Charts off by default: they are slow, and every assertion here is about
    # words rather than pictures.
    return render.render(build(conn, day_str, frame, **kwargs), with_charts=False)


def test_subject_carries_the_verdict_and_the_day(fixture_db):
    start, end = day_bounds("2026-08-05")
    out = rendered(fixture_db, "2026-08-05", build_day(start, end))
    # Written for a person, not a log: a sentence, the date they can recognise,
    # and the two numbers most likely to answer "what was it like there".
    assert out.subject.startswith(
        "REPLAY — Lake house Ecowitt System checks are good for Wed, Aug 5th"
    )
    # The high/low were dropped from the subject: they are the first thing in
    # the body, and a notification preview is short.
    assert "Low " not in out.subject
    assert "ATTENTION" not in out.subject
    # No emoji: a notification preview has to survive every surface it lands on.
    assert all(ord(c) < 0x2100 for c in out.subject)


def test_action_subject_names_the_condition_not_the_severity(fixture_db):
    start, end = day_bounds("2026-08-16")
    out = rendered(fixture_db, "2026-08-16", build_day(start, end, indoor=95.0, indoor_room=93.0))
    # ATTENTION is capitalised because the shape of the word is what the eye
    # catches before it reads anything.
    assert "checks need ATTENTION for Sun, Aug 16th" in out.subject
    assert "1 issue," in out.subject
    # The condition in plain words, not the check's internal name.
    assert "indoor 95" in out.subject
    assert "indoor within protection band" not in out.subject


def warn_day(start, end):
    """A day whose only complaint is a WARNING, with nothing failing.

    `indoor humidity in band` is the one check that can only ever WARN -- it is
    a comfort bound, and a check that cries failure over humidity trains people
    to ignore it. 64 % is above the 60 % band but below the 65 % the protection
    band starts caring about, so the day warns once and fails nothing.
    """
    frame = build_day(start, end)
    frame["indoor.humidity"] = 64.0
    return frame


def test_a_warning_day_reads_as_good_with_a_warning_not_as_attention(fixture_db):
    """R-010. Three states, three sentences -- and ATTENTION is not one of them here."""
    start, end = day_bounds("2026-09-12")
    out = rendered(fixture_db, "2026-09-12", warn_day(start, end))

    assert "are good with a WARNING for Sat, Sep 12th" in out.subject
    assert "ATTENTION" not in out.subject, "a warning is not a failure"
    # Capitalised on Marc's call, 2026-09-21. What separates the two loud
    # states is the verb -- "are good with" against "need" -- so that is what
    # is pinned, rather than the case of one word.
    assert "need ATTENTION" not in out.subject
    # It still says WHAT, the way the attention form does.
    assert "indoor humidity" in out.subject
    # And no issue count -- "1 issue" reads like a fault report.
    assert "issue" not in out.subject


def test_the_three_subject_forms_differ_before_the_date(fixture_db):
    """A phone notification shows the START of the line and nothing else.

    A difference that only appears after the date is a difference nobody sees,
    so this pins that the three forms diverge while they are still on screen.
    """
    # 🚨 ONE date for all three. Staged against three different dates this test
    # came back GREEN with the warning form collapsed into ATTENTION, because
    # the subjects still differed -- by date. Severity has to be the only thing
    # that varies, or the test is measuring the calendar.
    start, end = day_bounds("2026-09-12")

    subjects = {
        "ok": rendered(fixture_db, "2026-09-12", build_day(start, end)).subject,
        "warn": rendered(fixture_db, "2026-09-12", warn_day(start, end)).subject,
        "alert": rendered(
            fixture_db, "2026-09-12",
            build_day(start, end, indoor=95.0, indoor_room=93.0),
        ).subject,
    }
    assert len(set(subjects.values())) == 3

    # Compare the three at the point a notification truncates them. The prefix
    # is shared ("REPLAY — Lake house Ecowitt System checks "), so the first
    # difference has to arrive within a notification's worth of characters.
    heads = {k: v[:75] for k, v in subjects.items()}
    assert len(set(heads.values())) == 3, f"indistinguishable when truncated: {heads}"


def test_the_attention_form_is_pinned(fixture_db):
    """The loud form is the one that must not drift by accident."""
    start, end = day_bounds("2026-08-16")
    out = rendered(fixture_db, "2026-08-16", build_day(start, end, indoor=95.0, indoor_room=93.0))
    assert out.subject.startswith(
        "REPLAY — Lake house Ecowitt System checks need ATTENTION for Sun, Aug 16th - 1 issue, "
    )


def test_text_alternative_stands_alone_with_every_image_blocked(fixture_db):
    """§6.4. Verdict, numbers, action and banner, with no picture at all."""
    start, end = day_bounds("2026-08-16")
    report = build(fixture_db, "2026-08-16", build_day(start, end, indoor=95.0, indoor_room=93.0))
    out = render.render(report, with_charts=False)

    assert out.images == {}
    body = out.text
    assert "REPLAY" in body  # the banner
    assert "The lakehouse has been over 85 ºF" in body  # the verdict, in words
    assert "WHAT TO DO" in body  # the action
    assert "Outdoor High" in body  # the numbers
    assert "Dew Point High" in body  # added above humidity
    assert "WHAT IS STILL FINE" in body  # what is not broken
    # And nothing that only makes sense next to a picture.
    assert "see the chart" not in body.lower()


def test_replay_banner_appears_whenever_the_date_is_not_yesterday(fixture_db):
    start, end = day_bounds("2026-08-05")
    frame = build_day(start, end)

    replay = rendered(fixture_db, "2026-08-05", frame)
    assert "REPLAY" in replay.subject
    assert "does not describe current conditions" in replay.text
    assert "does not describe current conditions" in replay.html
    # Head AND foot: a long email on a phone is read from wherever the thumb
    # lands.
    assert replay.text.count("REPLAY — this report covers") == 2

    from reporting.report import yesterday

    current = rendered(fixture_db, "2026-08-05", frame, for_date=yesterday())
    assert "REPLAY" not in current.subject
    assert "does not describe current conditions" not in current.text


def test_alert_puts_the_conclusion_before_the_evidence(fixture_db):
    start, end = day_bounds("2026-08-16")
    out = rendered(fixture_db, "2026-08-16", build_day(start, end, indoor=95.0, indoor_room=93.0))
    body = out.text
    assert body.index("WHAT IS WRONG") < body.index("WHY WE THINK SO")
    assert body.index("WHAT TO DO") < body.index("YESTERDAY —")


def test_no_data_email_says_so_rather_than_going_quiet(fixture_db):
    start, end = day_bounds("2026-08-06")
    out = rendered(fixture_db, "2026-08-06", build_day(start, end, empty=True))
    assert "need ATTENTION for Thu, Aug 6th" in out.subject
    assert "no data for the day" in out.subject
    assert "issue" not in out.subject, "a no-data day has no issue count to give"
    assert "station or the pipeline is down" in out.text
    assert "no readings landed" in out.text


def test_html_is_email_safe(fixture_db):
    """No external stylesheet, no script, nothing that needs a network."""
    start, end = day_bounds("2026-08-05")
    out = rendered(fixture_db, "2026-08-05", build_day(start, end))
    html = out.html
    assert "<script" not in html.lower()
    assert "<link" not in html.lower()
    assert "http://" not in html and "https://" not in html
    assert "position:fixed" not in html


def test_charts_are_attached_and_referenced(fixture_db):
    start, end = day_bounds("2026-08-05")
    report = build(fixture_db, "2026-08-05", build_day(start, end))
    out = render.render(report, with_charts=True)

    assert set(out.images) == {"outdoor", "range", "rain", "indoor", "humidity"}, (
        "battery rides along only when a battery check is not green"
    )
    for name, png in out.images.items():
        assert png.startswith(b"\x89PNG")
        assert f'src="cid:{name}"' in out.html
    # §6.4: comfortably under 1 MB all in.
    assert sum(len(p) for p in out.images.values()) < 1_000_000


def test_battery_chart_only_rides_along_when_something_is_wrong(fixture_db):
    start, end = day_bounds("2026-08-20")
    report = build(fixture_db, "2026-08-20", build_day(start, end, battery_ch1=1.15))
    out = render.render(report, with_charts=True)
    assert "battery" in out.images


def test_run_length_is_marked_as_at_least_when_it_fills_the_window(fixture_db):
    """ "day 6 of this" — an alert that reads identically on day 6 and day 1
    trains people to skim it."""
    from reporting.render import _day_of

    assert _day_of({"days": 1}, 7) == ""
    assert _day_of({"days": 3}, 7) == " (day 3 of this)"
    assert _day_of({"days": 7}, 7) == " (day 7+ of this)"


def test_ordinal_dates_read_the_way_people_say_them():
    from datetime import date

    from reporting.render import friendly_date

    assert friendly_date(date(2026, 8, 5)) == "Wed, Aug 5th"
    assert friendly_date(date(2026, 8, 21)) == "Fri, Aug 21st"
    assert friendly_date(date(2026, 8, 22)) == "Sat, Aug 22nd"
    assert friendly_date(date(2026, 8, 23)) == "Sun, Aug 23rd"
    # The three the naive rule gets wrong.
    assert friendly_date(date(2026, 8, 11)).endswith("11th")
    assert friendly_date(date(2026, 8, 12)).endswith("12th")
    assert friendly_date(date(2026, 8, 13)).endswith("13th")


def test_the_timezone_is_not_printed_and_the_cadence_is(fixture_db):
    """Three readers who know where the house is do not need America/Chicago."""
    start, end = day_bounds("2026-08-05")
    out = rendered(fixture_db, "2026-08-05", build_day(start, end))
    assert "America/Chicago" not in out.text
    assert "America/Chicago" not in out.html
    assert "every 5 minutes" in out.text
    assert "every 5 minutes" in out.html


def test_the_station_link_is_configuration_not_a_constant(monkeypatch, fixture_db):
    """The URL carries the station id, so it never hard-codes into the repo."""
    start, end = day_bounds("2026-08-05")

    monkeypatch.delenv(config.ENV_STATION_URL, raising=False)
    bare = rendered(fixture_db, "2026-08-05", build_day(start, end))
    assert "ecowitt.net" not in bare.html
    assert "Live station" not in bare.text

    monkeypatch.setenv(config.ENV_STATION_URL, "https://example.net/station?id=1")
    linked = rendered(fixture_db, "2026-08-05", build_day(start, end))
    assert 'href="https://example.net/station?id=1"' in linked.html
    # Spelled out in the text alternative, where a link cannot be clicked.
    assert "https://example.net/station?id=1" in linked.text


def test_selftest_email_is_unmistakably_synthetic():
    from reporting import selftest

    out = render.render(selftest.synthetic_report(), with_charts=False)
    assert out.subject.startswith("SELFTEST — Lake house Ecowitt System checks need ATTENTION")
    assert "describes no real condition" in out.text
    assert "Nothing is wrong with the house" in out.text


def test_preview_writes_a_readable_file(tmp_path, fixture_db):
    """§8.5. The dry run produces the real email, not a description of one."""
    from reporting import send

    start, end = day_bounds("2026-08-05")
    report = build(fixture_db, "2026-08-05", build_day(start, end))
    out = render.render(report, with_charts=True)
    path = send.write_preview(out, report.for_date, tmp_path)

    assert path.exists()
    assert (path.parent / "email.txt").exists()
    assert (path.parent / "subject.txt").read_text().strip() == out.subject
    # cid: references are rewritten to the files beside it, so opening the
    # preview shows the charts rather than three broken images.
    html = path.read_text()
    assert 'src="indoor.png"' in html
    assert "cid:" not in html
    assert (path.parent / "indoor.png").exists()


def test_times_are_12_hour_and_line_up(fixture_db):
    """6:40 AM has to sit under 10:00 PM on the colon, not half a character left."""
    start, end = day_bounds("2026-08-05")
    out = rendered(fixture_db, "2026-08-05", build_day(start, end))
    lines = [ln for ln in out.text.splitlines() if " AM" in ln or " PM" in ln]
    assert lines, "the summary should carry clock times"
    assert not any(":" in ln and "24:" in ln for ln in lines)
    # Every time ends at the same column.
    assert len({len(ln.rstrip()) - ln.rstrip().rindex(":") for ln in lines}) == 1
    ends = {len(ln.rstrip()) for ln in lines}
    assert len(ends) == 1, f"times are ragged: {sorted(ends)}"


def test_the_flatline_check_is_gone(fixture_db):
    """Removed 2026-08-28: it warned on 4 of 27 days, every one a false alarm."""
    start, end = day_bounds("2026-08-05")
    report = build(fixture_db, "2026-08-05", build_day(start, end))
    assert "no flatlined sensor" not in list(report.checks.check)


def test_the_house_bar_uses_no_css_positioning(fixture_db):
    """Gmail strips `position:`, and the bar arrived as two broken fragments.

    Percent-width table cells are the one layout primitive every mail client
    has agreed on, so the band cannot come apart in transit.
    """
    start, end = day_bounds("2026-08-05")
    out = rendered(fixture_db, "2026-08-05", build_day(start, end))
    assert "position:" not in out.html
    assert "display:flex" not in out.html and "display:grid" not in out.html
    # The band is drawn, and drawn with tables.
    assert 'role="presentation"' in out.html
    assert out.html.count("<table") >= 3


def test_the_band_segments_span_exactly_the_width(fixture_db):
    """Widths that do not sum to 100% make the bar shorter than its own scale."""
    import re

    start, end = day_bounds("2026-08-16")
    out = rendered(fixture_db, "2026-08-16", build_day(start, end, indoor=95.0, indoor_room=93.0))

    # Every percent-width table in the email, checked independently: a row that
    # sums to 90% draws a bar that silently understates where the house sat.
    tables = re.findall(r"<table[^>]*>.*?</table>", out.html, re.S)
    checked = 0
    for table in tables:
        cells = re.findall(r"<td[^>]*>", table)
        # Only the fully-specified rows: the label row leaves its last cell
        # unsized on purpose so it takes up the slack.
        widths = [float(w) for w in re.findall(r'<td[^>]*width="([\d.]+)%"', table)]
        if not widths or len(widths) != len(cells):
            continue
        checked += 1
        assert abs(sum(widths) - 100) < 0.5, f"row sums to {sum(widths):.1f}%, not 100"
    assert checked >= 2, "expected the marker row and the scale row"


# --------------------------------------------------------------------------
# The rain chart (R-001)
#
# It plots a TRAILING 24-HOUR TOTAL, and there are two ways to get that wrong
# that both produce a chart which looks entirely reasonable: totalling the
# rolling series for the headline figure (about 24x too much), and drawing a
# window that has less than 24 hours behind it (too little, at the left edge,
# forever). Both are held down here rather than left to a reading of the code.
# --------------------------------------------------------------------------


class _WeekOnly:
    """The only thing the rain chart reads off a report is `week`."""

    def __init__(self, week):
        self.week = week


def rain_week(hourly_inches, *, start="2026-09-06 00:00"):
    """A 5-minute week frame whose `1_hour` reads back as the given hourly rain.

    `1_hour` is a ROLLING hour on the real station, and the chart samples it at
    each hour boundary with `last`. So only the final reading of each hour has
    to carry that hour's total for the fixture to be honest about what the
    resample sees -- and that reading lands ON the boundary, which is why the
    grid starts five minutes in: the hour ending 01:00 is the bucket
    (00:00, 01:00], and its last reading is the one stamped 01:00.
    """
    index = pd.date_range(start, periods=len(hourly_inches) * 12, freq="5min") + pd.Timedelta(
        minutes=5
    )
    values = []
    for inches in hourly_inches:
        values += [float("nan") if inches is None else 0.0] * 11
        values.append(float("nan") if inches is None else float(inches))
    return _WeekOnly(pd.DataFrame({"rainfall_piezo.1_hour": values}, index=index))


def test_rain_chart_plots_a_trailing_24_hour_total():
    """0.1 in in hour 0 is on the chart for 24 hours, then falls out of it."""
    hours = [0.1] + [0.0] * 40
    window = charts.rain_summary(rain_week(hours))["window"]

    # Hour 23 is the first point with a full 24 hours behind it, and that 24
    # hours contains the whole 0.1 in.
    assert window.iloc[23] == pytest.approx(0.1)
    # Still inside the window at hour 23 + 0, gone once hour 0 ages out.
    assert window.iloc[24] == pytest.approx(0.0), "the 0.1 in should have aged out"
    assert window.iloc[30] == pytest.approx(0.0)

    # And a run of rain accumulates across the window rather than being read
    # one hour at a time.
    spread = charts.rain_summary(rain_week([0.02] * 12 + [0.0] * 29))["window"]
    assert spread.iloc[23] == pytest.approx(0.24)


def test_rain_headline_is_the_last_days_biggest_window_not_the_week():
    """R-010. The title's number is the biggest 24 h ending in the LAST day.

    The same fixture pins both numbers precisely because they disagree: 0.24 in
    fell during the week, all of it six days ago, so the headline is 0.00 and
    the week total is 0.24. A title showing 0.24 here would tell three people it
    rained yesterday when it did not.
    """
    hours = [0.02] * 12 + [0.0] * 156  # a week, 0.24 in of it rain, all early
    summary = charts.rain_summary(rain_week(hours))

    assert summary["last_day_max"] == pytest.approx(0.0), "no rain ended in the last day"
    assert summary["total"] == pytest.approx(0.24), "the week total is the hourly sum"
    # What the wrong answer would look like, stated so the test says WHY it is
    # wrong rather than just asserting a number.
    rolling_sum = float(summary["window"].sum(skipna=True))
    assert rolling_sum > 5 * summary["total"], (
        "the fixture has to be able to tell the two apart -- if the rolling sum "
        "were close to the hourly one this test would pass on a broken chart"
    )


def test_a_storm_crossing_midnight_counts_at_full_size_in_the_headline():
    """The reason the headline reads a ROLLING window rather than a calendar day.

    0.24 in falls over eight hours, four before the last day starts and four
    after. A calendar-day total would report 0.12 and split the storm; the
    trailing window that ends inside the last day sees all of it.
    """
    hours = [0.0] * 140 + [0.03] * 8 + [0.0] * 20
    summary = charts.rain_summary(rain_week(hours))

    assert summary["last_day_max"] == pytest.approx(0.24), (
        "the window ending inside the last day has to reach back over midnight"
    )
    # State the wrong answer, so the test says why it is wrong.
    fell_on_the_last_day = sum(hours[144:])
    assert fell_on_the_last_day == pytest.approx(0.12)


def test_rain_leading_edge_is_blank_rather_than_short():
    """The first 23 hours have less than a day behind them. Draw nothing."""
    window = charts.rain_summary(rain_week([0.05] * 48))["window"]
    assert window.iloc[:23].isna().all(), "a partial window must not be drawn low"
    assert window.notna().iloc[23:].all()
    # min_periods=22 alone would have let these two through on the 22 and 23
    # readings that are all the frame has.
    assert pd.isna(window.iloc[21]) and pd.isna(window.iloc[22])


def test_rain_drops_a_window_with_more_holes_than_grid_coverage_allows():
    """Two missing hours is tolerated; three drops the window (90%, as §grid).

    Steady rain at 0.01 in/hour, so the arithmetic is easy to check by hand: the
    window ending at hour 31 spans hours 8-31, and every hour present in it
    contributes 0.01. A tolerated hole contributes nothing, which is why the
    answer is 0.22 rather than 0.24 -- a window with holes can only understate,
    and that is the whole reason for a floor on how many are allowed.
    """
    two_holes = [0.01] * 30 + [None, None] + [0.01] * 16
    window = charts.rain_summary(rain_week(two_holes))["window"]
    assert window.iloc[31] == pytest.approx(0.22), "22 of 24 hours present, at 0.01 each"

    three_holes = [0.01] * 30 + [None, None, None] + [0.01] * 15
    window = charts.rain_summary(rain_week(three_holes))["window"]
    assert pd.isna(window.iloc[32]), "21 of 24 is below 90%; draw nothing rather than 0.21"


def test_rain_chart_still_draws_a_dry_week():
    """A dry week is the common case here, and it must not look broken."""
    png = charts.rain(rain_week([0.0] * 168))
    assert png.startswith(b"\x89PNG")
    assert charts.rain_summary(rain_week([0.0] * 168))["total"] == pytest.approx(0.0)


def test_rain_hours_are_stamped_when_they_end_not_when_they_began():
    """A left-labelled resample put every point about an hour early.

    `1_hour` is a trailing total, so the reading at 01:00 is the rain that fell
    between 00:00 and 01:00 and belongs at 01:00. A plain `resample("1h")`
    labels that bucket 00:00, and the peak label then names the wrong hour.
    """
    hourly = charts._rain_hourly(rain_week([0.1] + [0.0] * 40, start="2026-09-06 00:00"))
    wet = hourly[hourly > 0]
    assert len(wet) == 1
    assert wet.index[0] == pd.Timestamp("2026-09-06 01:00"), (
        "the hour ending 01:00 must be stamped 01:00, not 00:00"
    )
