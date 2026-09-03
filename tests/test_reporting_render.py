"""Phase B: what the email actually says.

The property that matters most here is the one nobody notices until it fails:
**the text alternative has to stand alone.** Gmail defers images from unfamiliar
senders, and Stacy and Tad have never had mail from this address, so the first
few of these emails will arrive with every chart blocked. If the verdict, the
numbers, the action and the replay banner do not survive that, the email does
not work for the people it was written for.
"""

from __future__ import annotations

from conftest import build_day, day_bounds
from test_reporting_report import build

from reporting import config, render


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
