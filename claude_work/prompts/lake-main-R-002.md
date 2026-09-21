# lake-main-R-002 — round 2: exempt `1_hour`, keep 21 August failing

**Session:** `main` · **Register:** `claude_work/lake_request_register.md` (R-002)

**First, commit Cowork's edits sitting in the tree** — this prompt and the
register. Cowork does not write to git over the bridge (CLAUDE.md §14).

## Where round 1 left it

Round 1 stopped at step 1, correctly. Replaying 51 days gave 55 irregular
entries: 53 are `rainfall_piezo.1_hour`, and two are real —
`daily` 0.07→0.06 and `weekly` 0.10→0.09 at **2026-08-21 06:45**, when the
console re-zeroed and a 30-minute hole followed. Cowork corroborated it from the
21 Aug replay email (`13 irregular`, `283/288`, `longest single gap 25 min`).

**Decision (Cowork's): exempt `1_hour` only. 21 August keeps failing.** The
check fires once in 51 days on something that genuinely went backwards. That is
the opposite of "a warning that is usually nothing" (CLAUDE.md §14, trap 4), so
it stays. Round 1's second option — also forgiving a fall that coincides with a
re-zero — is rejected: it would have silenced the only real event on record.

Step 1 is done; don't redo it. Reuse round 1's replica and A/B harness.

## The change

1. **Exemption in the check, not the catalog.** A named module-level set in
   `notebooks/ecowitt_daily.py`, holding exactly `rainfall_piezo.1_hour`,
   commented with R-002 and the evidence. No pattern-matching on names. The
   catalog is not touched — it lives in the production database too, and
   `metric_accumulator_needs_last` ties `kind` to `resample_rule`. If you think
   the catalog should still change, report it as a finding with its migration.
2. **Replace the household-facing text** at `src/reporting/config.py:286-289`.
   It currently says "A known quirk of the piezo gauge", which is now false.
   After this round the check only fires on a real backwards step. **Do not
   state a cause**: the console re-zero is one observation, not a pattern.
   Match the plain register of the entries around it. Put before and after in
   the report — Marc approves it in the close, because it's what three people
   get told.

## What it changes, in numbers

`python -m reporting.matrix` over the whole record, before and after. Report:

- the days where this check's verdict changes. Expected: 8 flip to PASS, and
  21 Aug still FAILs with exactly 2 irregular entries (`daily`, `weekly`,
  06:45). **If the numbers differ from that, say so and say why before going
  on.**
- 🚨 **the day-level outcome, which is the number R-003 needs.** For each
  flipped day, is the email that day now *good*, or still ATTENTION because of
  another check? Use the email's own severity logic, not just this one check's
  verdict.

## Definition of done

- 🚨 **Two staged breaks, each naming the test that goes red:**
  1. remove the exemption → the 12 Sep `1_hour` decay FAILs again;
  2. widen the exemption to cover `rainfall_piezo.daily` → 21 Aug stops
     failing. This proves the guard still sees real backwards steps.
  Use **real 21 Aug and 12 Sep data as fixtures** if the test harness can hold
  them; synthetic series only if it can't, and say which you used.
- `pytest` green, count stated. `ruff check .` no worse than the 16 in
  `notebooks/audit.ipynb`.
- Render 12 Sep and 21 Aug to `data/reports/preview/` (dry run) and state both
  subject lines.
- **Commit locally. Do not push, do not deploy.** Deploying R-001 and R-002
  together is waiting on Marc.
- Add a **"Round 2"** section to `claude_work/reports/lake-main-R-002-report.md`.
  Leave round 1's text as it is.

## Traps

- `notebooks/ecowitt_daily.py` is production. `src/reporting/shared.py` and
  `explore_daily.ipynb` both import it.
- R-003 (the subject line for data-only failures) is out of scope. Measure for
  it; don't build it.
- `nb.ensure_db()` still connects to the Docker Postgres on 5433 (R-006). Use
  `LOCAL_PORT=5434 ./infra/tunnel.sh` as round 1 did, and close it after.
- Clock in **America/Los_Angeles**, explicitly.

## How the reply ends

```
/anthropic-skills:project-round-close lake-main-R-002
```

    **Start YYYY-MM-DD H:MM AM/PM / End H:MM AM/PM : MM:SS**

`TZ=America/Los_Angeles date +"%Y-%m-%d %-I:%M:%S %p"`
