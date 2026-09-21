# lake-main-R-002 — `rainfall_piezo.1_hour` is a rolling window tagged as a resetting accumulator

**Session:** `main` · **Register:** `claude_work/lake_request_register.md` (R-002)

## Why this round, and why now

Two of the five consecutive ATTENTION emails that went to Marc, Stacy and Tad on
9–13 Sep were `rain accumulators only reset to zero — 6 irregular`. Every cited
sample in the 12 Sep email is `rainfall_piezo.1_hour` stepping down in
consecutive five-minute slots (15:15→0.08, 15:20→0.06, 15:25→0.05) on a day with
0.09 in of rain. The email told the household it was "a known quirk of the piezo
gauge".

**The hypothesis:** `1_hour` is a trailing 60-minute total. It decays to
non-zero values by design every time rain ages out of its window. The catalog
tags it `kind='accumulator'` (`schema/metric_catalog_seed.sql:47`), and the
check at `notebooks/ecowitt_daily.py:354-367` flags any accumulator fall that
does not land on zero. So the check is wrong about the metric, not the metric
wrong about the rain. R-001 added a second piece of evidence: on 25 Aug `1_hour`
peaked at 0.17 in on a day whose `daily` finished at 0.09 in.

That is a hypothesis. **This round tests it before it fixes anything.**

## Step 1 — measure, and stop if the measurement disagrees

Replay the check over **every day since 2026-08-01** and list every irregular
entry it produces, grouped by metric. Report the table.

- **If every entry is `rainfall_piezo.1_hour`** — the hypothesis holds; go to
  step 2.
- **If any entry is another accumulator** (`daily`, `weekly`, `monthly`,
  `yearly`, `event`) — **stop.** Those are genuine backwards steps, the check is
  earning its keep on them, and the fix below would be incomplete. Report the
  offenders with timestamps and values, and hand back without changing code.

Also note from the replay whether `rainfall_piezo.event` resets to zero cleanly;
the catalog says "resets per event" and nobody has checked.

## Step 2 — the fix

**Exempt rolling totals from this one check, in the check. Do not reclassify
the catalog.** Cowork's call, and the reason: `kind` lives in the live database
on the VM as well as the seed, and `metric_accumulator_needs_last` couples it to
`resample_rule` — reclassifying is a migration on production for a problem one
check has. Name the exemption explicitly (a module-level set, commented with
R-002 and the evidence), not by pattern-matching metric names.

If, having done it, you think the catalog *should* change — report that as a
finding with the migration it would need. Do not do it.

**Correct the household-facing text.** `src/reporting/config.py:286-289` says
"A known quirk of the piezo gauge." After this round the check only fires on a
genuine backwards step, which is not a gauge quirk. Draft a replacement in the
same plain register the other entries use, and put before/after in the report —
Marc reads that text as what three people are told, so it is his to approve in
the close.

## Step 3 — what it changes, in numbers

Run `python -m reporting.matrix` over the whole record before and after. Report:

- how many days this check's verdict changes, and to what;
- how many of those days would have been ATTENTION emails that now go out as
  good — this is the number that decides whether R-003 (subject-line gating) is
  still worth building, so measure it rather than estimate it.

## Definition of done

- Step 1's table in the report, whichever way it came out.
- The check still **fails** on a genuine backwards step in a real accumulator.
  🚨 **Stage both breaks and name the test that went red for each:**
  1. a `daily` series falling 0.10 → 0.05 mid-day must still FAIL;
  2. remove the exemption and the 12 Sep `1_hour` decay must FAIL again.
  A guard nobody has watched fail is not a control.
- Tests live wherever the check is already tested; say where.
- `pytest` green, count stated. `ruff check .` no worse than its current 16,
  all in `notebooks/audit.ipynb`.
- Render 12 Sep 2026 to `data/reports/preview/` (dry run) and state its new
  subject line.
- **Commit locally. Do not push, do not deploy** — CLAUDE.md §14. Deploying
  R-001 and R-002 together is a decision waiting on Marc.

## Traps

- `notebooks/ecowitt_daily.py` is **production** — `src/reporting/shared.py`
  imports it. The notebook `explore_daily.ipynb` imports it too.
- `grid coverage`'s 90 % floor and the house checks are not this round's.
- R-003 (ATTENTION in the subject for a data-only failure) is out of scope.
- Clock in **America/Los_Angeles**, explicitly — R-001's first sitting came out
  two hours off by stamping Central.

## How the reply ends

Report to `claude_work/reports/lake-main-R-002-report.md`. Then the return
cell, then the clock line:

```
/anthropic-skills:project-round-close lake-main-R-002
```

    **Start YYYY-MM-DD H:MM AM/PM / End H:MM AM/PM : MM:SS**

`TZ=America/Los_Angeles date +"%Y-%m-%d %-I:%M:%S %p"`
