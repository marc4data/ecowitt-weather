# lake-main-R-013 — every day since install: how many hit 100 ºF

**Session:** `main` · **Register:** R-013

## 🚨 Read this first — how your reply ends, whatever happens

End your reply with these three things, in this order (CLAUDE.md §14):

1. `Report written: [lake-main-R-013-report.md](claude_work/reports/lake-main-R-013-report.md)`
2. The return cell, **exactly this, no slash, no prefix** — Marc pastes it into Cowork:
   ```
   project-round-close lake-main-R-013
   ```
3. `**Start YYYY-MM-DD H:MM AM/PM / End H:MM AM/PM : MM:SS**` — `TZ=America/Los_Angeles`

## Step 0

Commit Cowork's edits (the register and this prompt) — **only those two files.**
`notebooks/explore.ipynb` was already modified in the tree when this prompt was
written, not by Cowork. Leave it out of every commit and say in the report what
the change is.

## What Marc asked for

> add a section in the Explore notebook that does a version of the attached
> chart that includes all days since I installed the system. It's probably not
> going to have enough room to display the labels, so take them off and make a
> strong reference line at 100. I want to highlight how many days have been
> over 100 and how consistent that's been. Next to that graph, … a histogram
> that show max temp (rounded to nearest integer). Label x-axis, and then show
> # of days as labels with % of total underneath the # label. On the chart on
> the left, do an annotation that is X of Y days > 100F

## Where it goes

A new last section in **`notebooks/explore_daily.ipynb`**, headed something
like *"5. Every day since install — how often it hits 100 ºF"*. That notebook is
the one with trend sections; `explore.ipynb` is the schema explorer. If you
think it belongs elsewhere, say so in the report and put it in
`explore_daily.ipynb` anyway.

**Notebook only.** Don't change `src/reporting/` or the shared functions in
`notebooks/ecowitt_nb.py` / `ecowitt_daily.py` in any way that changes their
output — the 07:00 email imports them (CLAUDE.md §14, trap 1). Adding a new
function is fine; changing an existing one isn't.

## The data

- One row per **complete** local day (America/Chicago), from the first full day
  of data to yesterday. Today is partial, so leave it out. Say what the first
  day is — history starts 2026-08-01, with a stray 65-minute stub on 07-23 that
  isn't a day.
- Daily high and low of `outdoor.temperature` from the **5-minute** readings,
  not an hourly mean. The email's range chart already does it this way
  (`src/reporting/charts.py::temperature_range`), and a mean understates the
  peak.
- **"Over 100" is counted on the max rounded to the nearest integer**, so the
  annotation and the histogram can't disagree: a day at 100.4 ºF sits in the
  100 bar and does not count as over. State that rule once, in the section's
  markdown.

## The figure — two panels side by side, one row

**Left, wider (about 2:1): the daily range, every day.**
- One bar per day, from the low to the high, like the email's range chart
  (`docs/images/chart-four-weeks.png` shows its look). No value labels.
- A **strong** horizontal reference line at 100 ºF: heavier and darker than the
  gridlines, labelled "100 ºF" at its right end.
- Make the over-100 days stand out: bars whose rounded high is ≥ 101 in the
  accent colour, the rest muted.
- Annotation in clear space: **"X of Y days > 100 ºF"**, e.g. "38 of 51 days
  > 100 ºF".
- X axis: dates, with week or half-month ticks that don't collide.

**Right: histogram of the daily max, rounded to an integer.**
- One bar per integer ºF. X axis labelled "Daily high (ºF, rounded)".
- Above each bar, the day count, with the % of total days on a second line
  beneath it, e.g. `7` over `(14%)`. Skip empty bins.
- The same accent/muted split as the left panel (≥ 101 accent), and a vertical
  line at 100.5 marking the boundary.
- Share the y scale of neither panel with the other; they measure different
  things.

Palette and styling come from `nb.style()` / the existing palette, so it looks
like the rest of the notebook.

## "How consistent that's been"

Marc wants that highlighted. Just the X-of-Y annotation answers "how many", not
"how consistent". Also compute and state in the section's markdown the
**longest run of consecutive days over 100** and the dates it covered. Don't
add a third chart for it.

## Definition of done

- The cell runs top to bottom in the notebook's kernel against the real
  database. R-006: `nb.ensure_db()` picks up Docker on 5433, so use
  `LOCAL_PORT=5434 ./infra/tunnel.sh` and point the notebook at it, or fix it
  locally without committing a change to `ensure_tunnel`. Say which.
- **Cross-check the count a second way.** Count days with rounded high ≥ 101
  straight from a SQL `GROUP BY local date` and confirm it matches the pandas
  figure. Two methods agreeing is the test here, since a notebook cell has no
  pytest.
- Save the figure to `data/reports/preview/hot-days.png`, and **look at it**:
  no label collisions, the annotation doesn't sit on bars, the % lines don't
  overlap.
- Execute and save the notebook with outputs, the same way the other executed
  notebooks in the repo are kept.
- Commit locally. Pushing is fine — this is notebook-only, nothing to deploy.
- Report to `claude_work/reports/lake-main-R-013-report.md` with the X, Y,
  longest run and first day.

## Then end your reply exactly as the top of this prompt says.
