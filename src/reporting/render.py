"""Turn a Report into a subject, a text body, an HTML body and its images.

Pure, and that is the whole point of the module existing: the exact email can be
produced and read without a scheduler, without SMTP and without a database, so
tomorrow's email can be looked at today.

Two rules shape everything below.

**Conclusion, then evidence.** Never evidence with the conclusion left for the
reader to assemble. The verdict is the first line of both bodies, and on an
ACTION email what is wrong, since when and what to do all come before the data
that says so.

**The text alternative stands alone.** Gmail defers images from unfamiliar
senders, and Stacy and Tad have never received mail from this address. If every
image is blocked the email must still deliver its verdict, its numbers, its
action and -- on a replay -- its banner. So the text body is written first and
the HTML mirrors it, rather than the text being an afterthought stripped out of
the HTML.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

import pandas as pd

from . import config

LABELS = {"ok": "OK", "warn": "WATCH", "alert": "ACTION"}

# Email HTML is not web HTML: no flex, no grid, no external stylesheet, and
# inline styles on everything, because Gmail strips <style> blocks in some
# clients. Light background throughout -- these get printed.
INK = "#1b1b1b"
MUTED = "#6b6b6b"
RULE = "#dcdcd6"
SURFACE = "#ffffff"
VERDICT_COLOR = {"PASS": "#123a33", "WARN": "#4a3210", "FAIL": "#5e2716"}
VERDICT_BG = {"PASS": "#e2f0ec", "WARN": "#f9efd8", "FAIL": "#f7e4de"}
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"


@dataclass(frozen=True)
class Rendered:
    subject: str
    text: str
    html: str
    images: dict[str, bytes]


# --------------------------------------------------------------------------
# Subject
# --------------------------------------------------------------------------


def subject(report) -> str:
    """A sentence, not a status code.

        Lake house Ecowitt System checks are good for Wed, Aug 5th
        Lake house Ecowitt System checks are good with a warning for Sat, Sep 12th
            - indoor humidity 49-69 %
        Lake house Ecowitt System checks need ATTENTION for Fri, Aug 21st - 2 issues, indoor 94.8 ºF

    Written to be read by three people on a phone notification, only one of whom
    cares what a "check" is. `[lakehouse] ACTION -` was a machine's subject line:
    it sorted well and told a person nothing.

    Three forms, one per severity, and they diverge EARLY -- "are good" /
    "are good with a warning" / "need ATTENTION". A phone notification shows the
    start of the line and nothing else, so a difference that only appears after
    the date is a difference nobody sees (R-010).

    Three things are load-bearing:

    * **ATTENTION is capitalised and Good is not.** The shape of the word is
      what the eye catches before it reads anything.
    * **"warning" is lower case.** Only one of the three states is meant to
      pull someone off what they are doing; two shouting words would flatten
      that back into a single alarm.
    * **REPLAY still leads.** A truncated subject on a phone keeps its
      beginning, so anything that must not be mistaken for today goes first.

    A `warn` day carries no FAIL by construction -- `report._severity` reads
    `"alert" if fails else ("warn" if warns else "ok")` -- so the warning form
    can never be hiding a failure.
    """
    date_part = friendly_date(report.for_date)

    if report.severity == "ok" and report.has_data:
        head = f"Lake house Ecowitt System checks are good for {date_part}"
    elif report.severity == "warn" and report.has_data:
        # No issue count: a warning day is a single thing worth a glance, and
        # "1 issue" reads like a fault report.
        head = (
            f"Lake house Ecowitt System checks are good with a warning "
            f"for {date_part} - {_short_title(report)}"
        )
    else:
        head = f"Lake house Ecowitt System checks need ATTENTION for {date_part}"
        count = len([i for i in report.attention.get("items", []) if i.get("verdict") == "FAIL"])
        count = count or len(report.attention.get("items", []))
        # No count on a no-data day: "no data, no data for the day" was the
        # first thing this produced.
        issues = f"{count} issue{'s' if count != 1 else ''}, " if count else ""
        head += f" - {issues}{_short_title(report)}"

    if report.is_selftest:
        return f"SELFTEST — {head}"
    if report.is_replay:
        # Said twice on purpose: at the front where a truncated notification
        # keeps it, and at the end for anyone reading the full line.
        return f"REPLAY — {head} — not current conditions"
    return head


def friendly_date(when) -> str:
    """`Wed, Aug 5th` — how a person says a date, not how a database stores one."""
    day = when.day
    # 11th, 12th and 13th are the exceptions the naive rule gets wrong.
    suffix = "th" if 11 <= day % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{when:%a}, {when:%b} {day}{suffix}"


def _short_title(report) -> str:
    """The most important failure, in a few words rather than a check name."""
    items = report.attention.get("items", [])
    if not items:
        return "no data for the day"
    leading = items[0]
    measured = str(leading.get("measured") or "").split(" · ")[0].split(" — ")[0].strip()
    plain = {
        "indoor within protection band": f"indoor {measured}",
        "indoor climate holding": f"indoor climbing {measured}",
        "indoor humidity in band": f"indoor humidity {measured}",
        "sensors reporting recently": f"sensors quiet ({measured})",
        "no sensor dropped out": f"a sensor dropped out ({measured})",
        "battery levels": f"battery low ({measured})",
        "grid coverage": f"data gaps ({measured})",
        "longest single gap": f"a {measured} gap in the data",
        "runs covering the day": "the pipeline did not run",
        "day fully landed": "the day had not finished landing",
        "rows quarantined": f"{measured} rows quarantined",
        "values corrected after the fact": f"{measured} values corrected",
        "values physically possible": f"impossible readings ({measured})",
        "rain accumulators only reset to zero": "rain gauge totals went backwards",
    }.get(leading["check"], f"{leading['check']} — {measured}")
    return plain[:70]


def _station_link(text: str = "live station") -> str:
    """A small link out to the station's own page on ecowitt.net.

    Empty when `LAKEHOUSE_STATION_URL` is unset, which is the default: the URL
    carries the station id, so it is configuration rather than something this
    public repository should hard-code.

    An emoji rather than an image: a remote <img> would be blocked by the same
    image-deferral that the whole text alternative exists to survive, and an
    inline one costs bytes to say less than "📡" does.
    """
    url = config.station_url()
    if not url:
        return ""
    return (
        f' · <a href="{escape(url, quote=True)}" '
        f'style="color:#2a78d6;text-decoration:none;white-space:nowrap;">'
        f"📡 {escape(text)} &rsaquo;</a>"
    )


def _lookup(headlines: pd.DataFrame, measures: list[str]) -> dict[str, str]:
    if headlines is None or headlines.empty:
        return {}
    indexed = headlines.set_index("measure")
    return {m: str(indexed.loc[m, "value"]) for m in measures if m in indexed.index}


# --------------------------------------------------------------------------
# Shared fragments
# --------------------------------------------------------------------------


def banner_lines(report) -> list[str]:
    """The replay banner (§5.4). Part of rendering, never of the send path.

    Belt and braces: `--send --for-date` is already refused, but if a replay
    ever escapes that guard, no reader can mistake it for today. Because it
    lives here it is impossible to send a replay without it.
    """
    if report.is_selftest:
        return [
            "SELF-TEST — this email describes no real condition.",
            "It exists to prove the alerting path still works. Nothing is wrong with the house.",
        ]
    if not report.is_replay:
        return []
    return [
        f"REPLAY — this report covers {report.for_date:%A %d %B %Y}.",
        f"It was generated on {report.generated_at:%d %B %Y} and does not "
        "describe current conditions.",
    ]


def _day_of(item: dict, window_days: int) -> str:
    """ "day 6 of this" — so an alert does not read identically on day 6 and day 1.

    A run as long as the window may well be longer than the window, so it is
    reported as "6+" rather than claiming a precision the trend cannot support.
    """
    days = item.get("days") or 1
    if days <= 1:
        return ""
    return f" (day {days}{'+' if window_days and days >= window_days else ''} of this)"


def _since_line(report) -> str:
    """ "Thursday 13 August — 8 days before this report." (§6.3.2)

    A real date rather than "recently", and rather than the run length inside
    the 7-day trend, which saturates at the width of the window.
    """
    since = report.house.get("breach_since")
    if not since:
        return ""
    days = (report.for_date - since).days
    span = "the same day" if days == 0 else f"{days} day{'s' if days != 1 else ''} before"
    return (
        f"{since:%A %d %B %Y} — {span} this report. The house has been outside "
        "its protection band every day since."
    )


def _equipment_lines(report) -> list[str]:
    """One line per battery, only when something is not green (§6.2.6)."""
    problems = [e for e in report.equipment if e["verdict"] != "PASS"]
    if not problems:
        stale = [e for e in report.equipment if e["held_days"] is not None and e["held_days"] >= 30]
        line = "All sensors reporting, batteries healthy."
        if stale:
            # Not an alarm. A fresh alkaline AA legitimately holds a step for
            # weeks -- but "unchanged for 30 days" and "measured this morning"
            # should not read the same.
            line += " Unchanged for 30 days or more: " + ", ".join(e["label"] for e in stale) + "."
        return [line]
    lines = []
    for entry in problems:
        held = (
            f", unchanged for {entry['held_days']} days" if entry["held_days"] is not None else ""
        )
        basis = " (derived threshold, not a vendor figure)" if entry["basis"] == "derived" else ""
        lines.append(f"{entry['label']}: {entry['value']:.2f} V — {entry['verdict']}{held}{basis}")
    return lines


# --------------------------------------------------------------------------
# Text
# --------------------------------------------------------------------------


def text_body(report) -> str:
    lines: list[str] = []
    add = lines.append

    if banner := banner_lines(report):
        for line in banner:
            add(line)
        add("")

    add(report.one_line)
    add("")

    if report.severity == "alert":
        _text_action(report, add)

    add(f"YESTERDAY — {report.for_date:%A %d %B %Y}")
    add(
        f"  (the station reports every {config.SAMPLE_INTERVAL_MIN} minutes; "
        "each figure below is a single reading, not an average)"
    )
    if report.headlines is not None and not report.headlines.empty:
        label_w = max(len(str(m)) for m in report.headlines.measure) + 2
        value_w = max(len(str(v)) for v in report.headlines.value)
        # Times right-aligned so the colons line up: " 6:40 AM" sits under
        # "10:00 PM" rather than half a character to the left of it.
        when_w = max(len(str(w)) for w in report.headlines.when)
        for row in report.headlines.itertuples():
            add(
                f"  {str(row.measure).ljust(label_w)}"
                f"{str(row.value):>{value_w}}   {str(row.when):>{when_w}}"
            )
    else:
        add("  no readings landed for this day")
    add("")

    if report.comparison:
        add("HOW THAT COMPARES")
        add(f"  {report.comparison}")
        add("")

    house = report.house
    add("THE HOUSE")
    if house["high"] is None:
        add("  indoor: no readings")
    else:
        add(
            f"  indoor {house['low']:.1f}–{house['high']:.1f} ºF "
            f"(protection band {house['floor']:.0f}–{house['ceiling']:.0f} ºF)"
            + ("" if house["in_band"] else "  ** OUTSIDE THE BAND **")
        )
        if house["rh_high"] is not None:
            add(
                f"  humidity up to {house['rh_high']:.0f} % "
                f"(band tops out at {house['rh_ceiling']:.0f} %)"
            )
    add("")

    add("EQUIPMENT")
    for line in _equipment_lines(report):
        add(f"  {line}")
    add("")

    if report.severity == "warn":
        add("WORTH A GLANCE")
        for item in report.attention.get("items", []):
            add(
                f"  {item['check']}: {item['measured']}"
                f"{_day_of(item, report.attention.get('window_days', 0))}"
            )
        add("")

    add("CHECKS")
    if report.checks is not None and not report.checks.empty:
        for row in report.checks.itertuples():
            mark = {"PASS": "ok  ", "WARN": "WARN", "FAIL": "FAIL"}[row.verdict]
            add(f"  [{mark}] {row.check}: {row.measured}")
    else:
        add("  none ran — there was no data to check")
    add("")

    # Spelled out rather than linked: a text alternative cannot be clicked, and
    # a link nobody can follow is just a missing sentence.
    if url := config.station_url():
        add(f"Live station readings: {url}")
        add("")
    add(
        f"This arrives every morning at {config.SEND_TIME_HUMAN}. If it doesn't, "
        "something is wrong — tell Marc."
    )
    # Repeated at the foot as well as the head: a long email on a phone is read
    # from wherever the thumb lands, and a replay must not be mistakable for
    # today at either end of it.
    if banner := banner_lines(report):
        add("")
        for line in banner:
            add(line)
    return "\n".join(lines)


def _text_action(report, add) -> None:
    items = report.attention.get("items", [])
    failing = [i for i in items if i.get("verdict") == "FAIL"] or items
    window = report.attention.get("window_days", 0)

    if summary := report.summary:
        # Claude's rewrite goes ON TOP of the check-derived sections, never
        # instead of them. The measurements below are the source of truth, and
        # an email whose only account of the failure came from a model would
        # have no way to be right when the model was wrong.
        add("WHAT HAPPENED")
        add(f"  {summary['what_happened']}")
        add("")
        add("WHAT IT MEANS")
        add(f"  {summary['impact']}")
        add("")
        add(
            f"-- the two paragraphs above were written by {summary.get('model')}; "
            "everything below is the measured detail they are based on --"
        )
        add("")

    add("WHAT IS WRONG")
    for item in failing:
        add(f"  {item['check']}{_day_of(item, window)}")
        add(f"    {item['measured']}")
    add("")

    if since := _since_line(report):
        add("SINCE WHEN")
        add(f"  {since}")
        add("")

    add("WHAT TO DO")
    for line in report.actions:
        add(f"  - {line}")
    add("")

    add("WHY WE THINK SO")
    for item in failing:
        add(f"  {item['check']}: {item['note']}")
    add("")

    passing = (
        [row.check for row in report.checks.itertuples() if row.verdict == "PASS"]
        if report.checks is not None and not report.checks.empty
        else []
    )
    if passing:
        # An alert that does not say what is NOT broken makes people assume
        # everything is.
        add("WHAT IS STILL FINE")
        add(
            f"  {len(passing)} of {len(report.checks)} checks passed, including: "
            + ", ".join(passing[:4])
        )
        add("")


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------


def _p(
    content: str,
    *,
    size: str = "15px",
    color: str = INK,
    weight: str = "normal",
    top: str = "0",
    bottom: str = "12px",
) -> str:
    return (
        f'<p style="margin:{top} 0 {bottom} 0;font-family:{FONT};font-size:{size};'
        f'line-height:1.45;color:{color};font-weight:{weight};">{content}</p>'
    )


def _h(text: str) -> str:
    return (
        f'<p style="margin:26px 0 8px 0;font-family:{FONT};font-size:11px;'
        f"letter-spacing:0.08em;text-transform:uppercase;color:{MUTED};"
        f'border-bottom:1px solid {RULE};padding-bottom:4px;">{escape(text)}</p>'
    )


def html_body(report, images: dict[str, bytes]) -> str:
    blocks: list[str] = []

    if banner := banner_lines(report):
        blocks.append(
            f'<div style="background:{VERDICT_BG["WARN"]};border-left:4px solid #b8860b;'
            f'padding:10px 14px;margin:0 0 18px 0;">'
            + "".join(
                _p(escape(line), size="14px", color=VERDICT_COLOR["WARN"], bottom="4px")
                for line in banner
            )
            + "</div>"
        )

    tint = VERDICT_BG[
        "FAIL" if report.severity == "alert" else ("WARN" if report.severity == "warn" else "PASS")
    ]
    ink = VERDICT_COLOR[
        "FAIL" if report.severity == "alert" else ("WARN" if report.severity == "warn" else "PASS")
    ]
    blocks.append(
        f'<div style="background:{tint};padding:14px 16px;margin:0 0 6px 0;">'
        + _p(escape(report.one_line), size="18px", weight="600", color=ink, bottom="0")
        + "</div>"
    )
    # No timezone: every time in this email is a clock time at the house, and
    # three readers who know where the house is do not need to be told.
    blocks.append(_p(f"{report.for_date:%A %d %B %Y}{_station_link()}", size="13px", color=MUTED))

    if report.severity == "alert":
        blocks.append(_html_action(report))

    blocks.append(_h(f"Yesterday — {report.for_date:%d %B}"))
    blocks.append(_headline_table(report))
    blocks.append(
        _p(
            f"The station reports every {config.SAMPLE_INTERVAL_MIN} minutes. Each "
            "figure above is a single reading and the time it happened — not an "
            "average, which is why a peak here can sit above the line on a chart.",
            size="11px",
            color=MUTED,
            top="6px",
        )
    )

    if report.comparison:
        blocks.append(_h("How that compares"))
        blocks.append(_p(escape(report.comparison)))

    if "outdoor" in images:
        blocks.append(
            _img(
                "outdoor",
                "Outdoor temperature over the last 7 days, with each day's high and low labelled",
            )
        )
    if "range" in images:
        blocks.append(_h("Four weeks"))
        blocks.append(_img("range", "Daily outdoor high-to-low range, four Monday-to-Sunday weeks"))
    if "rain" in images:
        blocks.append(_h("Rain"))
        blocks.append(_img("rain", "Rainfall in any trailing 24 hours, over the last 7 days"))

    blocks.append(_h("The house"))
    blocks.append(_house_block(report))
    if "indoor" in images:
        blocks.append(
            _img("indoor", "Indoor temperature over 7 days against the protection limits")
        )
    if "humidity" in images:
        blocks.append(_img("humidity", "Indoor humidity over the last 7 days"))

    blocks.append(_h("Equipment"))
    for line in _equipment_lines(report):
        blocks.append(_p(escape(line), size="14px"))
    if "battery" in images:
        blocks.append(_img("battery", "Battery voltage, last 30 days"))

    if report.severity == "warn":
        blocks.append(_h("Worth a glance"))
        for item in report.attention.get("items", []):
            blocks.append(
                _p(
                    f"<strong>{escape(item['check'])}</strong>"
                    f"{escape(_day_of(item, report.attention.get('window_days', 0)))} — "
                    f"{escape(str(item['measured']))}",
                    size="14px",
                )
            )

    blocks.append(_h("Checks"))
    blocks.append(_check_table(report))

    blocks.append(
        f'<p style="margin:26px 0 0 0;padding-top:12px;border-top:1px solid {RULE};'
        f'font-family:{FONT};font-size:12px;color:{MUTED};line-height:1.5;">'
        f"This arrives every morning at {escape(config.SEND_TIME_HUMAN)}. "
        "If it doesn't, something is wrong — tell Marc.</p>"
    )

    return (
        f'<div style="background:{SURFACE};padding:18px;">'
        f'<div style="max-width:640px;margin:0 auto;">' + "".join(blocks) + "</div></div>"
    )


def _img(cid: str, alt: str) -> str:
    # width:100% with max-width keeps it inside a phone without upscaling on a
    # desktop; the alt text carries the meaning when images are blocked.
    return (
        f'<img src="cid:{cid}" alt="{escape(alt)}" '
        f'style="width:100%;max-width:640px;height:auto;display:block;'
        f'margin:10px 0 6px 0;border:1px solid {RULE};" />'
    )


def _headline_table(report) -> str:
    if report.headlines is None or report.headlines.empty:
        return _p("No readings landed for this day.", color=VERDICT_COLOR["FAIL"])
    rows = []
    for row in report.headlines.itertuples():
        rows.append(
            f'<tr><td style="padding:3px 14px 3px 0;font-size:14px;color:{MUTED};'
            f'white-space:nowrap;">{escape(str(row.measure))}</td>'
            f'<td style="padding:3px 12px 3px 0;font-size:15px;font-weight:600;'
            f'text-align:right;white-space:nowrap;">{escape(str(row.value))}</td>'
            # Right-aligned, so 6:40 AM and 10:00 PM line up on the colon.
            f'<td style="padding:3px 0;font-size:13px;color:{MUTED};'
            f'text-align:right;white-space:nowrap;">{escape(str(row.when))}</td></tr>'
        )
    # Capped rather than full-width: three short columns stretched across 640px
    # put the label and its number at opposite ends of the phone.
    return (
        f'<table cellpadding="0" cellspacing="0" border="0" '
        f'style="font-family:{FONT};width:auto;max-width:340px;">{"".join(rows)}</table>'
    )


def _house_block(report) -> str:
    house = report.house
    if house["high"] is None:
        return _p("No indoor readings for this day.", color=VERDICT_COLOR["FAIL"])

    # A band with a dot, not a number: "ten degrees above the line" is a
    # different fact from "95", and only one of them is readable at a glance.
    floor, ceiling = house["floor"], house["ceiling"]
    low, high = house["low"], house["high"]
    span_lo, span_hi = min(floor - 5, low - 2), max(ceiling + 15, high + 2)

    def pos(value):
        return max(0.0, min(100.0, 100.0 * (value - span_lo) / (span_hi - span_lo)))

    band_left, band_width = pos(floor), pos(ceiling) - pos(floor)
    mark_left, mark_width = pos(low), max(pos(high) - pos(low), 1.0)
    inside = house["in_band"]
    colour = VERDICT_BG["PASS" if inside else "FAIL"]
    edge = VERDICT_COLOR["PASS" if inside else "FAIL"]

    # ⚠️ TABLES, NOT POSITIONING. This was three absolutely-positioned divs,
    # which render correctly in a browser and are STRIPPED BY GMAIL -- so the
    # bar arrived as two broken fragments stacked above an empty box. Percent-
    # width table cells are the one layout primitive every mail client has
    # agreed on since the 1990s, and they cannot come apart.
    #
    # Two tables rather than one: each is 100% wide, so their percentages land
    # on the same pixels, and neither needs a cell to span the other's columns.
    def cells(segments):
        return "".join(
            f'<td width="{width:.1f}%" style="width:{width:.1f}%;height:{height}px;'
            f"line-height:{height}px;font-size:1px;background:{fill};"
            f'{extra}">&nbsp;</td>'
            for width, height, fill, extra in segments
            if width > 0.05
        )

    def table(inner):
        return (
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'border="0" style="width:100%;border-collapse:collapse;">'
            f"<tr>{inner}</tr></table>"
        )

    marker = table(
        cells(
            [
                (mark_left, 12, "transparent", ""),
                (mark_width, 12, colour, f"border:1px solid {edge};"),
                (100 - mark_left - mark_width, 12, "transparent", ""),
            ]
        )
    )
    scale = table(
        cells(
            [
                (band_left, 14, "#f0f0ec", f"border:1px solid {RULE};border-right:none;"),
                (band_width, 14, VERDICT_BG["PASS"], f"border:1px solid {RULE};"),
                (
                    100 - band_left - band_width,
                    14,
                    "#f0f0ec",
                    f"border:1px solid {RULE};border-left:none;",
                ),
            ]
        )
    )

    # The two numbers that define the band, under the edges they belong to.
    edges = (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'border="0" style="width:100%;border-collapse:collapse;">'
        f'<tr><td width="{band_left:.1f}%" style="font-family:{FONT};font-size:10px;'
        f'color:{MUTED};text-align:right;padding-top:2px;">{floor:.0f}</td>'
        f'<td width="{band_width:.1f}%" style="font-family:{FONT};font-size:10px;'
        f'color:{MUTED};text-align:right;padding-top:2px;">{ceiling:.0f} ºF</td>'
        f'<td style="font-size:10px;">&nbsp;</td></tr></table>'
    )
    bar = f'<div style="margin:6px 0 10px 0;">{marker}{scale}{edges}</div>'

    caption = (
        f"Indoor ran {low:.1f}–{high:.1f} ºF against a protection band of "
        f"{floor:.0f}–{ceiling:.0f} ºF."
    )
    if not inside:
        caption += " That is outside the band the house is meant to be held in."
        if house.get("breach_since"):
            caption += f" It has been outside since {house['breach_since']:%A %d %B}."
    if house["rh_high"] is not None:
        caption += (
            f" Humidity reached {house['rh_high']:.0f} % "
            f"(band tops out at {house['rh_ceiling']:.0f} %)."
        )
    return bar + _p(escape(caption), size="14px")


def _check_table(report) -> str:
    if report.checks is None or report.checks.empty:
        return _p("No checks ran — there was no data to check.", color=VERDICT_COLOR["FAIL"])
    rows = []
    for row in report.checks.itertuples():
        rows.append(
            f'<tr><td style="padding:3px 8px;font-size:11px;font-weight:700;'
            f"background:{VERDICT_BG[row.verdict]};color:{VERDICT_COLOR[row.verdict]};"
            f'text-align:center;white-space:nowrap;">{row.verdict}</td>'
            # The check's NAME never wraps: it is the row's identity, and
            # "values corrected after" / "the fact" split across two lines reads
            # as two different checks. `width:1%` plus nowrap is the old table
            # trick for "as narrow as the content allows, and no narrower".
            f'<td style="padding:3px 8px;font-size:13px;white-space:nowrap;width:1%;">'
            f"{escape(str(row.check))}</td>"
            # The measurement takes all the remaining width, and does the
            # wrapping for both of them.
            f'<td style="padding:3px 0;font-size:13px;color:{MUTED};width:99%;">'
            f"{escape(str(row.measured))}</td></tr>"
        )
    return (
        f'<table cellpadding="0" cellspacing="2" border="0" '
        f'style="font-family:{FONT};width:100%;table-layout:auto;">{"".join(rows)}</table>'
    )


def _html_action(report) -> str:
    items = report.attention.get("items", [])
    failing = [i for i in items if i.get("verdict") == "FAIL"] or items
    window = report.attention.get("window_days", 0)
    blocks = []
    if summary := report.summary:
        blocks.append(_h("What happened"))
        blocks.append(_p(escape(summary["what_happened"]), size="16px"))
        blocks.append(_h("What it means"))
        blocks.append(_p(escape(summary["impact"])))
        blocks.append(
            _p(
                f"The two paragraphs above were written by "
                f"{escape(str(summary.get('model')))}; everything below is the measured "
                "detail they are based on.",
                size="12px",
                color=MUTED,
            )
        )
    blocks.append(_h("What is wrong"))
    for item in failing:
        blocks.append(
            _p(
                f"<strong>{escape(item['check'])}</strong>"
                f"{escape(_day_of(item, window))}<br />{escape(str(item['measured']))}",
                size="15px",
            )
        )
    if since := _since_line(report):
        blocks.append(_h("Since when"))
        blocks.append(_p(escape(since)))
    blocks.append(_h("What to do"))
    blocks.append(
        '<ul style="margin:0 0 12px 0;padding-left:20px;font-family:'
        + FONT
        + ';font-size:15px;line-height:1.5;">'
        + "".join(f'<li style="margin-bottom:6px;">{escape(line)}</li>' for line in report.actions)
        + "</ul>"
    )
    blocks.append(_h("Why we think so"))
    for item in failing:
        blocks.append(
            _p(
                f"<strong>{escape(item['check'])}</strong> — {escape(str(item['note']))}",
                size="13px",
                color=MUTED,
            )
        )
    passing = [row.check for row in report.checks.itertuples() if row.verdict == "PASS"]
    if passing:
        blocks.append(_h("What is still fine"))
        blocks.append(
            _p(
                f"{len(passing)} of {len(report.checks)} checks passed, including "
                + escape(", ".join(passing[:4]))
                + ".",
                size="14px",
            )
        )
    return "".join(blocks)


# --------------------------------------------------------------------------


def render(report, *, with_charts: bool = True) -> Rendered:
    """Subject, both bodies, and the images they reference.

    The battery chart is attached only when a battery check is not green (§6.4):
    a voltage trace every morning is noise, and the same trace on the morning a
    cell is failing is the whole point.
    """
    images: dict[str, bytes] = {}
    if with_charts:
        from . import charts

        battery_bad = any(e["verdict"] != "PASS" for e in report.equipment)
        if report.checks is not None and not report.checks.empty:
            row = report.checks[report.checks.check == "battery levels"]
            battery_bad = battery_bad or (not row.empty and row.verdict.iloc[0] != "PASS")
        images = charts.render_all(report, include_battery=battery_bad)

    return Rendered(
        subject=subject(report),
        text=text_body(report),
        html=html_body(report, images),
        images=images,
    )
