# lake-main-R-001 — report

**Session:** `main` · **Branch:** `daily-email` · **Register:** R-001

The rain chart now plots a **trailing 24-hour total** instead of a 5-minute
rate. One function's worth of change, plus its alt text and its tests — and one
defect found on the way that was not in the prompt.

---

## 1. What changed

| What | Location | Before | After |
|---|---|---|---|
| The plotted series | [charts.py:517](src/reporting/charts.py#L517) | hourly `1_hour`, a rate | 24-period rolling sum of it |
| Y-axis | [charts.py:559](src/reporting/charts.py#L559) | `in / hour` | `in` |
| Title | [charts.py:561](src/reporting/charts.py#L561) | `Rain by the hour — last 7 days · {t} in in total` | `Rain in any 24 hours — last 7 days · {t} in in total` |
| Peak label | [charts.py:477](src/reporting/charts.py#L477) | none | `0.15 in · 24 h to Fri 11, 7 am` |
| Hourly resample | [charts.py:415](src/reporting/charts.py#L415) | `resample("1h")` | `resample("1h", label="right", closed="right")` — see §3 |
| Where the numbers come from | [charts.py:450](src/reporting/charts.py#L450) | inline in `rain()` | `rain_summary()`, pure and testable |
| Alt text | [render.py:488](src/reporting/render.py#L488) | "Rainfall by the hour over the last 7 days" | "Rainfall in any trailing 24 hours, over the last 7 days" |

The other five charts are untouched. The email still carries exactly
`outdoor`, `range`, `rain`, `indoor`, `humidity`, with `battery` riding along
only when a battery check is not green.

## 2. The three traps

**The week total.** It comes from the **hourly** series, not the rolling one, and
that is now the only place in the module where it is computed —
`rain_summary()` at [charts.py:450](src/reporting/charts.py#L450). A test holds
it there (§4). For the week ending 12 Sep the rolling sum would have read
**4.50 in** against the true **0.24 in**.

**The leading edge.** 🚨 **It ripples, so per the prompt I stopped and am
reporting it rather than widening the fetch.** `report.week` is **one frame
shared by four charts** — `rain()`, `outdoor()` and both `_indoor_panel()`
callers all read `report.week` directly
([charts.py:182](src/reporting/charts.py#L182),
[charts.py:315](src/reporting/charts.py#L315),
[charts.py:413](src/reporting/charts.py#L413)) and all three of the others title
themselves "last 7 days". Widening `gather`'s fetch to 8 days
([report.py:186](src/reporting/report.py#L186)) would silently give them an 8th
day of trace under a 7-day title, and would move the labelled daily
high/low marks on the outdoor chart. That is past `gather` and the bucket
constants.

So, **not** `min_periods=1`: the first 23 hours are **blanked outright** and
drawn as a blank, with a muted `no full 24 hours yet` in the gap. A partial
window is never drawn low. The follow-up — give the rain chart its own 8-day
frame, or widen `week` and trim the other three — is a separate round; I have
not minted a number for it.

I also closed the IAP tunnel I opened on port 5434.

**Gaps.** Stated in the docstring at
[charts.py:433](src/reporting/charts.py#L433) and pinned to the standard the
email already uses: a 24-hour window needs **≥ 90% of its hours**
(`RAIN_MIN_HOURS = 22`), which is the same 90% floor `grid coverage` uses to
call a day reportable. Up to two missing hours are tolerated and count as no
rain; a third drops the window to blank rather than drawing it 0.01 low.

## 3. 🚨 The finding — the hourly series was mislabelled by an hour

**Not in the prompt. Found by cross-checking the chart's own numbers against a
second source, which is the only reason it surfaced.**

`resample("1h").last()` labels each bucket by its **left** edge, but `last`
takes the reading at the **right** one. `1_hour` is a trailing total, so the
point stamped `06:00` was actually the hour ending `06:55` — the entire series
sat about an hour later than its own labels.

It was invisible while nothing on the chart named a time. This round's peak
label names one, so it would have shipped a wrong hour to three people.

Measured, against `rainfall_piezo.daily` over 6–12 Sep 2026:

| calendar day | daily accumulator | right-labelled (now) | left-labelled (before) |
|---|---|---|---|
| 10 Sep | 0.10 in | **0.10** ✅ | 0.10 ✅ |
| 11 Sep | 0.06 in | 0.05 (−0.01) | 0.05 (−0.01) |
| 12 Sep | 0.09 in | **0.09** ✅ | 0.10 (+0.01) ❌ |
| **week** | **0.25 in** | **0.24 in** | 0.25 in |

⚠️ **Read that bottom row carefully.** The old code's week total was *right*,
and right for the wrong reason: it was a cent-inch low on the 11th and a
cent-inch high on the 12th and the two cancelled. The new total is 0.24 because
it is honest about the 11th. I changed it and said so rather than keeping a
number that matched by luck.

The residual 0.01 in is `1_hour`'s own quantisation — sampling a 0.01-in-resolution
trailing total once an hour loses a cent-inch of an event that straddles a
boundary. Closing it means differencing the accumulator, which is **R-002's
ground**; I have not touched it. Recorded in the docstring at
[charts.py:404](src/reporting/charts.py#L404).

**I departed from the prompt here.** It said resample "exactly as today". I kept
the load-bearing half (`last`, never `sum`) and fixed the labelling, because
this round is what makes the error visible on the chart.

## 4. Tests — six new, in `test_reporting_render.py`

| Test | Holds down |
|---|---|
| `test_rain_chart_plots_a_trailing_24_hour_total` | 0.1 in is in the window for 24 h, then falls out |
| `test_rain_headline_total_is_the_hourly_sum_not_the_rolling_sum` | 🚨 the week total |
| `test_rain_leading_edge_is_blank_rather_than_short` | first 23 hours blank, incl. hours 21 and 22 that `min_periods` alone would pass |
| `test_rain_drops_a_window_with_more_holes_than_grid_coverage_allows` | 2 holes tolerated, 3 drops the window |
| `test_rain_chart_still_draws_a_dry_week` | the dry path still produces a PNG |
| `test_rain_hours_are_stamped_when_they_end_not_when_they_began` | §3 |

`107 passed` (was 101). `ruff check .` reports **16 errors, all in
`notebooks/audit.ipynb`** — the same 16 it started with, none in any file this
round touched.

### 🚨 Staged breaks — three, and the tests that went red

| Break | Red |
|---|---|
| `"total": float(window.sum(...))` — total from the rolling series | `test_rain_headline_total_is_the_hourly_sum_not_the_rolling_sum` — `assert 1.56 == 0.24 ± 2.4e-07` |
| `min_periods=1`, leading-edge blanking removed | `test_rain_leading_edge_is_blank_rather_than_short`, `test_rain_drops_a_window_with_more_holes_than_grid_coverage_allows` |
| `resample("1h")` — labelling reverted | `test_rain_hours_are_stamped_when_they_end_not_when_they_began` + 3 others |

All three restored; `107 passed` after each.

## 5. Rendered and looked at

Two real days, dry-run, nothing sent. Both are under `data/reports/`, which is
gitignored — the paths are on marcs-macbook-pro-local.

| day | what it exercises | output |
|---|---|---|
| **12 Sep 2026** | a real 3-day event, 0.24 in over the week | `data/reports/preview/2026-09-12/rain.png` |
| **5 Sep 2026** | a completely dry week | `data/reports/preview/2026-09-05/rain.png` |

**12 Sep** reads: flat at zero to Thu 10, a ramp to a labelled peak of
**0.15 in · 24 h to Fri 11, 7 am**, a decay as that rain ages out, then Sat 12's
0.09 in entering at the right edge. The storm appears **once, at its true
size** — which is the thing the round was for. The first day is blank with
`no full 24 hours yet` in it.

**5 Sep** reads: the zero floor at 0–0.10 in, `no rain in the last 7 days`
centred, `0.00 in in total` in the title. It looks like a dry week rather than a
broken chart.

One cosmetic fix after first looking: the blank-region note was centred on the
blank span, which always starts at the frame edge, so it printed through the
`in` axis label. It is now anchored left with a 6 pt inset.

## 6. Two things for Cowork that are not R-001

1. ⚠️ **`nb.ensure_db()` will connect you to the wrong database.**
   [ecowitt_nb.py:158](notebooks/ecowitt_nb.py#L158) `ensure_tunnel` treats
   "something is listening on 127.0.0.1:5433" as "the tunnel is up". On this
   machine **a Docker container currently holds 5433**
   (`com.docke 48557`), so `ensure_db()` handed me a stranger's Postgres, which
   failed with `password authentication failed for user "ecowitt_ro"` — an
   error that reads like a credential problem and is not one. `infra/tunnel.sh`
   already defends against exactly this
   ([tunnel.sh:112](infra/tunnel.sh#L112): "listening proves SOMETHING owns the
   port, not that WE do"); the notebook helper does not. I worked around it with
   `LOCAL_PORT=5434 ./infra/tunnel.sh` and did **not** change `ensure_db`.
   Worth a number.
2. ⚠️ **A fragment of the read-only DB password reached this session's
   transcript.** psycopg echoed it inside an unparsed-DSN error before I
   switched to building the DSN with `quote_plus` in Python. Nothing was
   committed and nothing left the machine, but `ecowitt-readonly-password`
   contains a shell-hostile character and is now partly in a log. Rotating it is
   cheap; Marc's call.
3. **R-002 evidence, unsolicited:** on 2026-08-25 `rainfall_piezo.1_hour` peaked
   at **0.17 in** on a day whose `rainfall_piezo.daily` finished at **0.09 in**.
   A trailing hour spanning midnight exceeds either calendar day's total —
   consistent with R-002's "rolling window tagged as a resetting accumulator"
   hypothesis. Not acted on.

## 7. What I did not do

- Did **not** widen the fetch (§2), and did not route around it with
  `min_periods=1`.
- Did **not** touch `schema/metric_catalog_seed.sql` or the
  `rain accumulators only reset to zero` check. The 12 Sep preview still fails
  that check — subject line `1 issue, rain totals went backwards` — exactly as
  it did before this round. That is R-002.
- Did **not** change `CLAUDE.md` or the register; both were already modified in
  the working tree when this round opened.
- Nothing was sent. Both renders are dry runs.

---

## 8. Second sitting — independent verification, 2026-09-17 10:24 PM

Marc reopened the round in Code with `/anthropic-skills:project-round-close
lake-main-R-001`. The round was already executed, so this sitting **verified the
report against the repository instead of re-running it**. A build report is a
claim; this is the check.

| Claim in this report | How it was checked | Result |
|---|---|---|
| `rain_summary()`, `RAIN_MIN_HOURS`, right-labelled resample, blanking | `grep` for each symbol | all present — [charts.py:377](src/reporting/charts.py#L377), [:415](src/reporting/charts.py#L415), [:445](src/reporting/charts.py#L445), [:450](src/reporting/charts.py#L450) |
| six new tests | `grep -n "def test_rain"` | all six present, [test_reporting_render.py:319-387](tests/test_reporting_render.py#L319) |
| `107 passed` | `python -m pytest -q` | **107 passed** |
| `ruff`: 16 errors, all in `notebooks/audit.ipynb` | `ruff check .`, filtered | **16 errors, none outside `audit.ipynb`** |
| both days rendered | `ls data/reports/preview/` | `2026-09-12/rain.png` and `2026-09-05/rain.png` both present |
| alt text reworded | `grep` in `render.py` | present, [render.py:488](src/reporting/render.py#L488) |

### The staged break, re-staged

🚨 **Not taken on the report's word — re-run.** `"total": float(hourly.sum(...))`
was replaced with `window.sum(...)` and the guard alone was run:

```
assert summary["total"] == pytest.approx(0.24), "the week total is the hourly sum"
E   assert 1.56 == 0.24 ± 2.4e-07
tests/test_reporting_render.py:342: AssertionError
1 failed in 0.39s
```

`test_rain_headline_total_is_the_hourly_sum_not_the_rolling_sum` **went red, with
the same 1.56 the first sitting reported.** Restored; `107 passed`; no
`STAGED BREAK` string left anywhere in `src/` or `tests/`.

### An instrument caught, and it was mine

Looking at `2026-09-12/rain.png` I read a **break in the trace** between Sat 12
and the right-edge block, and was about to file it as an undeclared dropped
window. Before writing it down I measured the PNG instead of the impression —
sampling the trace colour `(108,159,221)` on the known flat-zero stretch, fixing
the zero row at `y=316`, and walking every column for a trace pixel within ±2px:

| columns with no pixel on the zero row | what it is |
|---|---|
| `x=60..196` (137 px ≈ 24.2 h) | the deliberate leading-edge blank — matches the 23 blanked points |
| `x=675..884` | the storm; the trace is legitimately *above* zero |
| `x=927..1005` | the Sat 12 shower; also above zero |

**`x=885..926` has an unbroken zero line.** The gap was never there — it was a
thin line read off a 1024-px render. The chart is correct, and the finding would
have been against working code. Recorded because the near-miss is the point:
the eye was the instrument, and it was the thing that needed checking.

Corroborating, from the same preview run's `email.txt`: 12 Sep had
`grid coverage: 287/288 slots (99.7%)` and `longest single gap: 5 min`, so a
three-hour hole was ruled out independently of the pixels.

### One thing the second sitting noticed

The dry week (`2026-09-05`) blanks its first 23 hours like any other, but
carries **only** `no rain in the last 7 days` — no `no full 24 hours yet` in the
blank. Almost certainly right (two notes on an empty chart is clutter), and it
is **not** raised as a defect. Noted so the choice is a decision on the record
rather than an oversight nobody spotted.

Nothing was committed in this sitting either.

---

**Start 2026-09-17 6:06 PM / End 10:28 PM : 4:22:00 (2 sittings — 16:18 building, 04:00 verifying)**
