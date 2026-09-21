# lake-main-R-013 — report

**Every day since install: how many hit 100 ºF**

**Session:** `main` · **Branch:** `daily-email` · **Register:** R-013

---

## The numbers

| | |
|---|---|
| **X of Y** | **44 of 51 days over 100 ºF** |
| **First day** | **2026-08-01** — the first day with a day's worth of readings |
| **Last day** | 2026-09-20 (yesterday; today is partial and excluded) |
| **Longest run** | **18 consecutive days, 4 Aug to 21 Aug** |
| Range of daily highs | 90 ºF to 115 ºF |
| Most common high | **106 ºF, 14 days (27%)** |

Section added as **"5. Every day since install — how often it hits 100 ºF"** in
[notebooks/explore_daily.ipynb](notebooks/explore_daily.ipynb), before the
`nb.shutdown()` teardown so that stays last. Figure at
`data/reports/preview/hot-days.png` (gitignored).

## 🚨 The cross-check disagreed, and that was the point of it

First run: **pandas said 44 of 51, SQL said 44 of 50.** X agreed, Y did not.

Not arithmetic — **the two methods encoded two different definitions of
"complete day".** The pandas path used a coverage filter only to *find the first
day*, then took every day in the contiguous range after it. The SQL applied the
filter to *every* day, which dropped **2026-08-03 (251 of 288 slots, 87%)** out
of the middle of the series.

**Resolved by stating the rule once and having both methods read it:** every
local day from 2026-08-01 through yesterday, **contiguous, nothing dropped from
the middle**. A hole in "every day since install" would misstate both the
picture and the Y in "X of Y". Re-run, both give **44 of 51**, and 51 is exactly
the number of calendar days in the range — checked.

⚠️ **The cost of that choice, stated rather than buried:** 2026-08-03 is the one
day below the 90% coverage floor the email uses to call a day reportable. Its
high is 97.2 ºF. If its missing 13% contained the real peak, that day could in
principle belong on the other side of 100 and X would be 45. Keeping it is the
lesser distortion, but it is a judgement, not a measurement.

## The guard, and it went red for real before it was staged

The cell carries an `assert` comparing the pandas figure to the SQL one. **It is
not a hypothetical — it is the check that caught the disagreement above**, while
the round was being built.

Staged deliberately as well, against the **shipped cell text extracted from the
notebook** (123 lines, the real bytes), with the cross-check pointed at a
one-day-shorter window:

```
AssertionError: pandas 44/51 vs SQL 44/50
-> the cross-check guard went RED, as it must
```

A notebook cell has no pytest, so two methods agreeing is the test here, and the
`assert` is what makes it a control rather than a comment.

## The figure

Two panels, one row, 1.95:1.

**Left — every day, low to high.** One bar per day, no value labels. A heavy
`100 ºF` rule at 100, labelled at its right end. Days whose rounded high is ≥ 101
in the accent colour, the rest muted. `44 of 51 days > 100 ºF` in the clear
space bottom-left.

**Right — the daily high as a distribution.** One bar per integer ºF, count over
percent above each bar, empty bins skipped, dashed boundary at 100.5. Separate
y-scale, as asked: one panel counts degrees, the other counts days.

### The rounding rule, and a thing worth knowing about it

Stated once in the section's markdown: **over 100 means the rounded high is ≥ 101**,
so a day at 100.4 sits in the 100 bar and does not count.

✅ **In this record the rule never actually bites** — no day rounds to 100 or to
101. The highs jump from 99 (2 days) straight to 102. The rule still governs both
panels so they cannot disagree, but nobody should think it is doing work here.

### Two layout defects found by looking, not by rendering

The skill's last step is to open the image. Both of these passed "the code ran":

1. **Histogram labels collided.** Two-line labels on neighbouring one-day bars
   overlapped — `(2%)(2%)` ran together at 92/93 and again at 112/113. Fixed by
   lifting the second label of any touching pair of small bars.
2. **The left x-axis lied about spacing.** Ticking on calendar dates 1/8/15/22
   silently skipped 29 August, so Aug 22 → Sep 1 looked like a normal week. Now
   every 7th day from the start, evenly spaced.

Re-rendered and looked at again: no collisions, the annotation sits clear of the
bars, the percent lines are legible.

### Colour was validated, not eyeballed

Accent `#eb6834` (the palette's orange, already the email range chart's colour)
against the project's own `nb.MUTED` `#898781`:

```
[PASS] Lightness band       [PASS] CVD separation  ΔE 9.8 (protan) · 21.6 (tritan)
[PASS] Normal-vision floor  ΔE 17.6                [PASS] Contrast vs surface  all ≥ 3:1
```

The project's existing `MUTED` passes every applicable check, so nothing new was
invented. A first candidate (`#9a9890`) came back with a contrast **WARN** at
2.81 — below 3:1, which the skill treats as non-dismissable — and was dropped.

⚠️ **One check FAILs and is out of scope, said plainly:** the chroma floor flags
`#898781` as "reads gray". That check is for *categorical* palettes where hue
carries identity. Here the split is emphasis, not identity — grey is the
intended reading, and identity is carried by the 100 ºF rule, the dashed
boundary and the annotation, never by colour alone.

⚠️ **The validator silently did nothing the first two times.** Run as `.js` it
threw `SyntaxError: Unexpected token 'export'`; copied to `vp.mjs` it exited
**0 with no output**, which reads like a pass. Its CLI guard is
`process.argv[1].endsWith("validate_palette.js")`, so a renamed copy never runs.
An exit code of 0 from a tool that printed nothing is not a pass.

## Where it went, and what was left alone

- **`explore_daily.ipynb`**, per the prompt. Agreed: that is the notebook with
  the trend sections; `explore.ipynb` is the schema explorer.
- **Nothing in `src/reporting/` or the shared notebook modules was changed.**
  `git status` shows `notebooks/ecowitt_nb.py` and `ecowitt_daily.py` clean, so
  the 07:00 email is untouched.

### R-006 — how the notebook reached the database

`nb.ensure_db()` probes `127.0.0.1:5433`, which a Docker container still holds.
**Chosen route: fixed locally without committing.** `TUNNEL_PORT` was pointed at
5434 for the duration of the run against `LOCAL_PORT=5434 ./infra/tunnel.sh`,
then reverted — `git status notebooks/ecowitt_nb.py` is clean, verified after the
run. The committed cell calls plain `nb.ensure_db()` and carries no workaround,
because R-006 is the place to fix this once.

The whole notebook was executed top to bottom in its own kernel:
**21 cells executed, none errored**, outputs kept, which matches how the
committed version was stored (20 cells with outputs before this round).

## `notebooks/explore.ipynb` — the file left out of every commit

As instructed. The change is **execution artifacts, not source**: `execution_count`
filled in from null, `outputs` captured, and the `"id"` keys reordered within
each cell by a newer nbformat writer. Somebody ran the notebook. No code or
markdown differs.

---

**Start 2026-09-21 11:50 AM / End 11:59 AM : 08:29**
