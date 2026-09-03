"""The inline charts, as PNG bytes.

Embedded as CID parts so they render without a click and without a login, and
drawn with the notebooks' own palette and styling so the email and the notebook
look like one system rather than two.

Three rules carried over from the notebook, none of them cosmetic:

  * **Gaps are drawn as gaps.** The frames arrive reindexed onto a complete time
    grid, so a dropout is NaN and matplotlib leaves a visible break. Bridging it
    would draw a line through readings that were never taken.
  * **Readable in greyscale.** Limits are dashed lines rather than shaded
    bands: a tint behind a trace mutes the trace, and these get printed.
  * **Legible at phone width.** Wide-and-short, large type, few series.

Nothing here decides *whether* a chart is worth sending -- `render` does that.
"""

from __future__ import annotations

import io
import math

import matplotlib

matplotlib.use("Agg")  # no display on the VM, and none wanted in a test

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mticker  # noqa: E402
import pandas as pd  # noqa: E402

from .shared import daily, nb  # noqa: E402

# Phone-first: 1000 px wide at 100 dpi, and short enough that the whole chart is
# on screen with the text above it still visible.
FIGSIZE = (10.0, 3.4)
DPI = 100

BAND_FILL = "#eef3f1"  # protection band; survives greyscale
BREACH_FILL = "#f7e4de"  # the same tint `VERDICT_FILL` uses for FAIL
HIGHLIGHT = "#f6efdc"  # the notebook's daylight sand, reused for "this day"


def _png(fig) -> bytes:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=DPI, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return buffer.getvalue()


def _empty(title: str) -> bytes:
    fig, ax = plt.subplots(figsize=FIGSIZE, layout="constrained")
    ax.text(
        0.5,
        0.5,
        "no data in this window",
        transform=ax.transAxes,
        ha="center",
        va="center",
        color=nb.MUTED,
        fontsize=11,
    )
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title(title, loc="left", fontsize=11, color=nb.INK)
    return _png(fig)


def _reference_line(ax, value, label, *, color):
    """A limit line, deliberately heavier than the grid and labelled in place.

    Shading the safe band was the first attempt and it was worse: a tint behind
    everything muted the traces it was supposed to frame, and it made a normal
    day look like a warning. A line says the same thing and gets out of the way.
    """
    ax.axhline(value, color=color, linewidth=1.4, linestyle=(0, (6, 3)), zorder=2)
    ax.annotate(
        label,
        xy=(0.998, value),
        xycoords=ax.get_yaxis_transform(),
        xytext=(0, 3),
        textcoords="offset points",
        ha="right",
        va="bottom",
        fontsize=8.5,
        color=color,
        zorder=6,
    )


def _nice_axis(ax, values, *, step, include=()):
    """Round the axis out to whole multiples of `step`, and tick on them.

    Matplotlib's autoscaling produced gridlines at 67.5 and 72.5 ºF, which is a
    resolution nobody reads a house at. Rounding the limits outwards means every
    gridline lands on a multiple of five and the top and bottom of the plot are
    themselves round numbers.
    """
    lows = [float(min(values)), *[float(v) for v in include]]
    highs = [float(max(values)), *[float(v) for v in include]]
    span = max(max(highs) - min(lows), step)
    bottom = math.floor((min(lows) - span * 0.10) / step) * step
    top = math.ceil((max(highs) + span * 0.14) / step) * step
    ax.set_ylim(bottom, top)
    ax.yaxis.set_major_locator(mticker.MultipleLocator(step))


def _mark_extreme(ax, series, label, how, *, color, avoid=(), clearance=0.0):
    """Mark and label the single hottest or coldest point on the whole chart.

    One label per chart rather than one per line: with four rooms drawn, eight
    labels is a thicket, and the question being asked is "how hot did the house
    get", not "how hot did each room get".
    """
    if series.dropna().empty:
        return
    clean = series.dropna()
    stamp = clean.idxmax() if how == "max" else clean.idxmin()
    value = float(clean.loc[stamp])

    # Put the label on the outside of the point by default -- above a peak,
    # below a trough -- but flip it inwards when that would land it on a limit
    # line. A peak of 83.4 under an 85 ºF limit printed its label straight
    # through the dashes.
    outward = how == "max"
    if any(abs(float(line) - value) < clearance for line in avoid):
        outward = not outward

    # A label centred on a point at the very edge of the plot hangs over the
    # axis. Anchor it inward instead once it is within a tenth of either end.
    left, right = ax.get_xlim()
    fraction = (mdates.date2num(stamp) - left) / (right - left) if right > left else 0.5
    align = "left" if fraction < 0.10 else ("right" if fraction > 0.90 else "center")

    ax.plot([stamp], [value], "o", color=color, markersize=5, zorder=7)
    ax.annotate(
        f"{value:.1f} · {label}",
        xy=(stamp, value),
        xytext=(0, 10 if outward else -10),
        textcoords="offset points",
        ha=align,
        va="bottom" if outward else "top",
        fontsize=9,
        color=nb.INK,
        zorder=8,
        bbox={
            "boxstyle": "round,pad=0.22",
            "facecolor": nb.SURFACE,
            "edgecolor": "none",
            "alpha": 0.85,
        },
    )


# Colour is keyed to the ROOM, not to the drawing order. Slot-based colour looks
# identical until a series is dropped from one chart and not another -- then the
# Basement is orange above and green below, and the two charts quietly stop
# agreeing with each other.
ROOM_COLORS = {
    "Basement": nb.SERIES_COLORS[1],
    "Living Room": nb.SERIES_COLORS[2],
    "Office/Bedroom": nb.SERIES_COLORS[3],
    "indoor": nb.SERIES_COLORS[0],
}


def _room_series(report, leaf):
    """The paired room sensors for one measurement, as hourly averages.

    ⚠️ THE CONSOLE IS DELIBERATELY NOT HERE. `indoor.temperature` is what the
    protection check keys on -- it sits with the thermostat and is authoritative
    -- but it is also the noisiest trace on the chart, because it sees the
    compressor cycle directly. The summary table still reports it as Indoor
    High/Low; this chart is about the rooms.

    Hourly means, not the 5-minute grid: at native resolution the sawtooth is
    the whole picture and the shape of the week disappears underneath it.
    """
    out = []
    for metric in daily.indoor_sensors(report.meta, leaf=leaf):
        if metric == f"indoor.{leaf}" or metric not in report.week.columns:
            continue
        series = report.week[metric]
        if not series.notna().any():
            continue
        location = report.meta[metric]["location"]
        out.append((location, series.resample("1h").mean()))
    return sorted(out)


def _indoor_panel(report, *, leaf, title, unit, limit, limit_label, step, floor=None):
    """One indoor chart: the rooms, hourly, against their limit."""
    nb.style()
    series = _room_series(report, leaf)
    if not series:
        return _empty(title)

    fig, ax = plt.subplots(figsize=(FIGSIZE[0], FIGSIZE[1] * 1.1), layout="constrained")
    for location, values in series:
        ax.plot(
            values.index,
            values.values,
            label=location,
            color=ROOM_COLORS.get(location, nb.SERIES_COLORS[4]),
            linewidth=1.6,
            zorder=4,
        )

    _reference_line(ax, limit, f"{limit_label}  {limit:.0f} {unit}", color="#a8442a")

    combined = pd.concat([values for _, values in series])
    include = [limit]
    show_floor = floor is not None and float(combined.min()) <= floor + 15
    if show_floor:
        include.append(floor)

    # The hottest and coldest points anywhere on the chart, named by room.
    limits = [v for v in include]
    span = max(max(combined.max(), *limits) - min(combined.min(), *limits), step)
    hottest = max(series, key=lambda pair: pair[1].max())
    coldest = min(series, key=lambda pair: pair[1].min())
    _mark_extreme(
        ax,
        hottest[1],
        hottest[0],
        "max",
        color=ROOM_COLORS.get(hottest[0], nb.INK),
        avoid=limits,
        clearance=span * 0.10,
    )
    _mark_extreme(
        ax,
        coldest[1],
        coldest[0],
        "min",
        color=ROOM_COLORS.get(coldest[0], nb.INK),
        avoid=limits,
        clearance=span * 0.10,
    )

    if show_floor:
        _reference_line(ax, floor, f"Lower limit  {floor:.0f} {unit}", color="#2a6ea8")
    elif floor is not None:
        # In the title, not the plot: as an in-plot annotation it sat in the
        # bottom-left corner, which is exactly where a cold extreme's label
        # lands, and the two overprinted each other.
        title = f"{title}  ·  lower limit {floor:.0f} {unit} is off-chart"

    _nice_axis(ax, combined.dropna(), step=step, include=include)
    ax.set_ylabel(unit)
    ax.set_title(title, loc="left", fontsize=11, color=nb.INK)
    # The legend goes OUTSIDE the axes, under the plot. Inside at upper-left it
    # sat exactly where the hottest-point label lands, and the two printed on
    # top of each other -- "94.6 · Office/Bedroom" through "Basement  Living
    # Room  Office/Bedroom". `plot_realm` in the notebook already places
    # legends this way for the same reason.
    handles, labels = ax.get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="outside lower center",
        ncol=len(series),
        frameon=False,
        fontsize=9,
    )
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%a %d"))
    return _png(fig)


def indoor(report) -> bytes:
    """Room temperatures over 7 days, hourly, against the protection limits."""
    return _indoor_panel(
        report,
        leaf="temperature",
        title="Indoor temperature — last 7 days, hourly averages",
        unit="ºF",
        limit=daily.PROTECT_MAX_F,
        limit_label="Upper limit",
        step=5.0,
        floor=daily.PROTECT_MIN_F,
    )


def indoor_humidity(report) -> bytes:
    """Room humidity over 7 days, hourly. Damp is the slow way a house is lost."""
    return _indoor_panel(
        report,
        leaf="humidity",
        title="Indoor humidity — last 7 days, hourly averages",
        unit="%",
        limit=daily.PROTECT_RH_WARN,
        limit_label="Upper limit",
        step=5.0,
    )


def outdoor(report) -> bytes:
    """Outdoor temperature over 7 days, every day's high and low labelled.

    The context for everything else: an indoor number means something different
    on a 102 ºF day than on a 78 ºF one.

    Humidity is deliberately not here any more. It was a second panel that
    doubled the height of the chart to answer a question nobody was asking of
    it -- the summary table already carries the day's humidity range, and dew
    point above it says more about how the air felt.

    The high and low of each day are marked and labelled on the line itself
    rather than described underneath. A reader scanning the shape wants to know
    which peak was 105 without counting gridlines.
    """
    nb.style()
    temp = report.week.get("outdoor.temperature")
    if temp is None or temp.dropna().empty:
        return _empty("Outdoor temperature — last 7 days")

    fig, ax = plt.subplots(figsize=(FIGSIZE[0], FIGSIZE[1] * 1.15), layout="constrained")

    start, end = report.day.index.min(), report.day.index.max()
    if start is not None and end is not None:
        ax.axvspan(start, end, color=HIGHLIGHT, zorder=0, linewidth=0)

    ax.plot(temp.index, temp.values, color=nb.SERIES_COLORS[1], zorder=3)

    # One high and one low per calendar day, taken from the drawn series so the
    # label always sits exactly on the line rather than near it.
    clean = temp.dropna()
    for _, day_values in clean.groupby(clean.index.normalize()):
        # A sliver of a day at either edge of the window has a high and a low
        # within a degree of each other, and the two labels land on top of one
        # another. Six hours is enough of a day to have a shape worth marking.
        if len(day_values) < 6:
            continue
        for how, offset, valign in (("max", 8, "bottom"), ("min", -8, "top")):
            stamp = day_values.idxmax() if how == "max" else day_values.idxmin()
            value = day_values.loc[stamp]
            ax.plot([stamp], [value], "o", color=nb.SERIES_COLORS[1], markersize=3.5, zorder=4)
            ax.annotate(
                f"{value:.0f}",
                xy=(stamp, value),
                xytext=(0, offset),
                textcoords="offset points",
                ha="center",
                va=valign,
                fontsize=8.5,
                color=nb.INK,
                zorder=5,
            )

    # Headroom for the labels, which otherwise collide with the axes.
    low, high = float(clean.min()), float(clean.max())
    pad = max((high - low) * 0.14, 3.0)
    ax.set_ylim(low - pad, high + pad)

    ax.set_ylabel("ºF")
    ax.set_title(
        "Outdoor temperature — last 7 days  ·  shaded is the day reported below",
        loc="left",
        fontsize=11,
        color=nb.INK,
    )
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%a %d"))
    return _png(fig)


def rain(report) -> bytes:
    """Rain by the hour, over the last 7 days.

    Read from `rainfall_piezo.1_hour` -- the station's own "how much fell in the
    last hour" -- rather than differencing the daily total. Both would agree,
    but the accumulator resets at midnight and differencing across a reset is
    exactly the arithmetic `rain accumulators only reset to zero` exists to
    catch. Measuring the thing directly avoids having to be careful.

    Seven days rather than one: most days here are dry, and a flat line at zero
    for 24 hours tells nobody anything. A week shows when it last actually
    rained, which is the question behind the question.
    """
    nb.style()
    rolling = report.week.get("rainfall_piezo.1_hour")
    if rolling is not None and rolling.notna().any():
        # The week arrives on the station's 5-minute grid (so the outdoor
        # chart's peaks match the summary table). `1_hour` is a ROLLING total,
        # so the value at each hour boundary is that hour's rain -- resample
        # with `last`, never `sum`, which would count every reading twelve
        # times over.
        hourly = rolling.resample("1h").last()
    else:
        # Fall back to the daily accumulator, differenced hour on hour. A fall
        # that is not a reset cannot be negative rain, so the floor at zero is
        # safe.
        total = report.week.get("rainfall_piezo.daily")
        if total is None or total.dropna().empty:
            return _empty("Rain by the hour — last 7 days")
        total = total.resample("1h").last()
        delta = total.diff()
        hourly = delta.where(delta >= 0, total).clip(lower=0)

    fig, ax = plt.subplots(figsize=FIGSIZE, layout="constrained")
    ax.plot(hourly.index, hourly.values, color=nb.SERIES_COLORS[0], linewidth=1.4)
    ax.fill_between(
        hourly.index, 0, hourly.fillna(0).values, color=nb.SERIES_COLORS[0], alpha=0.18, linewidth=0
    )

    week_total = float(hourly.sum(skipna=True))
    ax.set_ylabel("in / hour")
    ax.set_title(
        f"Rain by the hour — last 7 days  ·  {week_total:.2f} in in total",
        loc="left",
        fontsize=11,
        color=nb.INK,
    )
    # A dry week is a real answer, and an autoscaled flat line at zero looks
    # like a broken chart rather than a dry week. Give it a floor to sit on.
    if week_total <= 0.001:
        ax.set_ylim(0, 0.1)
        ax.annotate(
            "no rain in the last 7 days",
            xy=(0.5, 0.5),
            xycoords="axes fraction",
            ha="center",
            va="center",
            fontsize=10,
            color=nb.MUTED,
        )
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%a %d"))
    return _png(fig)


def temperature_range(report) -> bytes:
    """Four Monday-to-Sunday weeks of daily high-to-low bars.

    Each bar spans the day's true low to its true high, read from the 5-minute
    data rather than from an hourly mean -- a mean understates a peak, and this
    chart is a comparison of peaks.

    The y-axis deliberately does NOT include zero. Nothing outdoors here goes
    near 0 ºF, so a zero baseline would compress every bar into the top third
    and throw away the differences the chart exists to show.
    """
    nb.style()
    frame = report.extremes
    if frame is None or frame.empty or "outdoor_high" not in frame:
        return _empty("Daily temperature range — last 4 weeks")
    frame = frame.dropna(subset=["outdoor_high", "outdoor_low"]).copy()
    if frame.empty:
        return _empty("Daily temperature range — last 4 weeks")

    # Four whole weeks ending with the week the reported day falls in, so the
    # bars always line up Monday-to-Sunday and week-on-week is a fair read.
    monday = report.for_date - pd.Timedelta(days=report.for_date.weekday())
    first = pd.Timestamp(monday) - pd.Timedelta(weeks=3)
    grid = pd.date_range(first, periods=28, freq="D")

    frame["day"] = pd.to_datetime(frame["day"])
    frame = frame.set_index("day").reindex(grid)

    fig, ax = plt.subplots(figsize=(FIGSIZE[0], FIGSIZE[1] * 1.2), layout="constrained")
    lows = frame.outdoor_low.to_numpy(dtype=float)
    highs = frame.outdoor_high.to_numpy(dtype=float)
    positions = range(len(grid))

    ax.bar(
        positions,
        highs - lows,
        bottom=lows,
        width=0.62,
        color=nb.SERIES_COLORS[1],
        alpha=0.85,
        zorder=3,
    )

    # Every mark labelled, as integers: the point of the chart is comparing
    # numbers between days, and reading them off an axis is worse than reading
    # them off the bar.
    for x, (low, high) in enumerate(zip(lows, highs, strict=True)):
        if pd.isna(low) or pd.isna(high):
            continue
        ax.annotate(
            f"{high:.0f}",
            xy=(x, high),
            xytext=(0, 3),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=8,
            color=nb.INK,
            zorder=4,
        )
        ax.annotate(
            f"{low:.0f}",
            xy=(x, low),
            xytext=(0, -3),
            textcoords="offset points",
            ha="center",
            va="top",
            fontsize=8,
            color=nb.MUTED,
            zorder=4,
        )

    finite = [v for v in [*lows, *highs] if not pd.isna(v)]
    span = max(finite) - min(finite)
    ax.set_ylim(min(finite) - span * 0.18, max(finite) + span * 0.16)

    # Major ticks on the week boundaries, minor ticks on the days.
    ax.set_xticks([i for i in positions if i % 7 == 0])
    ax.set_xticklabels([f"{grid[i]:%b %d}" for i in positions if i % 7 == 0], fontsize=9)
    ax.set_xticks(list(positions), minor=True)
    ax.set_xticklabels([f"{d:%a}"[0] for d in grid], minor=True, fontsize=7)
    ax.tick_params(axis="x", which="minor", length=0, pad=14, colors=nb.MUTED)
    for boundary in [i - 0.5 for i in positions if i % 7 == 0][1:]:
        ax.axvline(boundary, color=nb.AXIS, linewidth=1.0, zorder=1)
    ax.set_xlim(-0.8, len(grid) - 0.2)

    ax.set_ylabel("ºF")
    ax.set_title(
        "Daily outdoor range — 4 weeks, Monday to Sunday  ·  each bar is that day's low to high",
        loc="left",
        fontsize=11,
        color=nb.INK,
    )
    return _png(fig)


def battery(report) -> bytes:
    """Battery voltages over 30 days.

    Attached only when a battery check is not PASS -- see `render`. The
    capacitor is drawn on its own axis: it swings 4.0-5.3 V daily by design, and
    plotting it against a 1.6 V cell would flatten the cell into a line.
    """
    nb.style()
    metrics = [
        m
        for m in daily.BATTERY_LIMITS
        if m in report.month.columns and report.month[m].notna().any()
    ]
    if not metrics:
        return _empty("Battery voltage — last 30 days")

    fig, ax = plt.subplots(figsize=FIGSIZE, layout="constrained")
    twin = None
    for slot, metric in enumerate(metrics):
        series = report.month[metric]
        color = nb.SERIES_COLORS[slot % len(nb.SERIES_COLORS)]
        label = metric.rsplit(".", 1)[-1]
        if metric.endswith("capacitor"):
            twin = twin or ax.twinx()
            twin.plot(
                series.index,
                series.values,
                color=color,
                linewidth=1.0,
                alpha=0.7,
                label=f"{label} (right)",
            )
            twin.set_ylabel("V — capacitor")
            twin.grid(False)
        else:
            ax.plot(series.index, series.values, color=color, label=label)
            limit = daily.BATTERY_LIMITS[metric]
            ax.axhline(limit["warn"], color=nb.AXIS, linewidth=0.8, linestyle="--")

    ax.set_ylabel("V — cells")
    ax.set_title(
        "Battery voltage — last 30 days  ·  dashed lines are the warning floors",
        loc="left",
        fontsize=11,
        color=nb.INK,
    )
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=5))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    handles, labels = ax.get_legend_handles_labels()
    if twin is not None:
        extra = twin.get_legend_handles_labels()
        handles, labels = handles + extra[0], labels + extra[1]
    ax.legend(handles, labels, loc="lower left", frameon=False, fontsize=8.5, ncol=4)
    return _png(fig)


def render_all(report, *, include_battery: bool) -> dict[str, bytes]:
    """Every chart the email will carry, keyed by its CID name.

    Never raises. A chart that fails to draw costs the email a picture; an
    exception here would cost the email itself, and the text alternative already
    carries every number these charts show (§6.4).
    """
    # Order is reading order in the email: the day in context, then the month
    # it sat in, then rain, then the house, then equipment only when it is not
    # green.
    wanted = {
        "outdoor": outdoor,
        "range": temperature_range,
        "rain": rain,
        "indoor": indoor,
        "humidity": indoor_humidity,
    }
    if include_battery:
        wanted["battery"] = battery

    images = {}
    for name, draw in wanted.items():
        try:
            images[name] = draw(report)
        except Exception as exc:  # never raise from the report path
            print(
                f"WARNING: could not draw the {name} chart "
                f"({type(exc).__name__}: {exc}); sending without it"
            )
    return images
