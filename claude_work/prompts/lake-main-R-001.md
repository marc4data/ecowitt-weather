# lake-main-R-001 — the rain chart reports a rate, not an amount

**Session:** `main` · **Register:** `claude_work/lake_request_register.md` (R-001)

## What Marc asked for

> Instead of it reporting the amount of rain in the observation (a 5-min
> snapshot). I'd like the chart to show rain total for a running 24 hours. So,
> rain totals accumulate for 24 hours then fall out of the calculation once the
> lag is outside the 24-hour window.

## Why it is worth doing

`src/reporting/charts.py::rain()` currently plots `rainfall_piezo.1_hour`
resampled to hourly `last()`, y-axis `in / hour`, over 7 days. That answers *was
it coming down hard* and never *how much fell*. A storm that runs 8 p.m. to
4 a.m. is split by every calendar boundary the reader might apply, and on a dry
week the chart is a flat line at zero apologising for itself.

A trailing 24-hour total answers the question people actually have, and shows an
event once, at its true size.

## The change

**One function: `src/reporting/charts.py::rain()`.** Keep the 7-day window —
Marc's call, 2026-09-17, so rain stays beside the other three 7-day charts.

1. **Keep `rainfall_piezo.1_hour` as the source.** Do not difference an
   accumulator. The existing docstring already explains why, and R-002 below is
   live evidence that differencing accumulators here is a minefield.
2. Resample to hourly `last()` exactly as today — that is the per-hour
   increment, and `last` rather than `sum` is load-bearing (the frame arrives on
   the 5-minute grid, so `sum` counts every reading twelve times).
3. Plot a **24-period rolling sum** of that hourly series. Every point is the
   rain that fell in the 24 hours before it.
4. Y-axis becomes inches, not `in / hour`. Title along the lines of
   `Rain in any 24 hours — last 7 days · {total:.2f} in in total`.
5. Label the peak with its value and when the 24 hours ended, if there was one.
6. The dry-week path must still work — the zero floor and the
   "no rain in the last 7 days" annotation.

### Three traps, in the order they will bite

🚨 **The week total must NOT come from the rolling series.** Summing 168 rolling
24-hour values counts every hour roughly 24 times. Keep computing the total from
the **hourly** series. If the headline figure jumps by an order of magnitude,
this is why.

⚠️ **The leading edge has no 24 hours behind it.** The first 23 hours of a
7-day frame cannot carry a full window. Preferred fix: widen the fetch by one
day and plot the last 7, so every point on the chart is a complete 24 hours.
**If that ripples past `report.py::gather` and the bucket constants, stop and
report it** — do not route around it with `min_periods=1`, which silently
understates the left edge of every chart.

⚠️ **Gaps.** An hour with no reading resamples to NaN. Decide explicitly what a
rolling sum does across one, say so in the docstring, and make it consistent
with how `grid coverage` already talks about holes.

### Out of scope, deliberately

**Do not touch `schema/metric_catalog_seed.sql` or the
`rain accumulators only reset to zero` check.** That is R-002, a separate round,
because it changes what three people receive at 07:00 and needs its own staged
break. If this round learns something about it, **report it** — do not fix it.

## Definition of done

- `rain()` produces the new chart; the six-chart set is otherwise unchanged.
- Rendered and **looked at** for two real days: **12 Sep 2026** (0.09 in, a real
  event) and a dry day of your choosing. Both attached to the report or written
  to `data/reports/`.
- Tests: extend whichever module already covers the charts. At minimum, a test
  that a known hourly series produces the expected 24-hour rolling values, and
  a test that the headline total is the hourly sum rather than the rolling sum.
- 🚨 **Stage a break and name the test that went red.** A guard nobody has
  watched fail is not a control. The obvious one: make the total come from the
  rolling series and confirm the total test fails. "All tests pass" is not
  evidence.
- `ruff check .` no worse than it starts. It currently reports 16 errors, all in
  `notebooks/audit.ipynb`; leave them, they are not this round's.
- Write the report to `claude_work/reports/lake-main-R-001-report.md`.

## How the reply ends

Return handoff cell, then the clock line, in that order. **Marc pastes the cell
into Cowork, which is where the round is reviewed and closed.** Plain English
rather than a slash command — `project-round-close` is installed in Cowork but
not in this one (observed 2026-09-17), and a cell that only works on one surface
is a cell that fails silently on the other.

```
Review round lake-main-R-001 — report at claude_work/reports/lake-main-R-001-report.md
```

    **Start YYYY-MM-DD H:MM AM/PM / End H:MM AM/PM : MM:SS**

Measured, not estimated — take the start timestamp before the first edit.
`TZ=America/Los_Angeles date +"%Y-%m-%d %-I:%M:%S %p"`
