# lake-main-R-002 — report

**`rainfall_piezo.1_hour` is a rolling window tagged as a resetting accumulator**

**Session:** `main` · **Branch:** `daily-email` · **Register:** R-002

---

## 🛑 The round stopped at Step 1, as the prompt instructed

> *"If any entry is another accumulator (`daily`, `weekly`, `monthly`, `yearly`,
> `event`) — **stop.** … Report the offenders with timestamps and values, and
> hand back without changing code."*

**Two of the 55 irregular entries are not `1_hour`.** No code was changed. Steps
2 and 3 were not started.

The hypothesis is *mostly* right — 53 of 55, and 8 of 9 failing days — but
"mostly" is exactly the case the stop condition exists for, and the exemption as
specified would have hidden a real event.

## 1. Step 1 — every irregular entry since 2026-08-01, grouped by metric

51 days replayed, every one of them with data.

| metric | entries | span |
|---|---|---|
| `rainfall_piezo.1_hour` | **53** | 2026-08-07 … 2026-09-20 |
| `rainfall_piezo.daily` | **1** | 2026-08-21 |
| `rainfall_piezo.weekly` | **1** | 2026-08-21 |
| | **55** | |

### The offenders, with timestamps and values

Both land in the same five-minute slot, on one day:

| metric | local timestamp | fell from | to |
|---|---|---|---|
| `rainfall_piezo.daily` | 2026-08-21 06:45 | 0.07 in | **0.06 in** |
| `rainfall_piezo.weekly` | 2026-08-21 06:45 | 0.10 in | **0.09 in** |

### They are real, not a resampling artifact

🚨 **An alarming measurement gets checked before anything is done about it.** The
replay reads a 5-minute-bucketed frame, so a bucketing artifact was the first
thing to rule out. Raw `observation` rows, `America/Chicago`:

```
local_ts             1_hour  daily  event  monthly  rain_rate  weekly  yearly
2026-08-21 06:40:00    0.04   0.07   0.07     0.12       0.02    0.10    0.17
2026-08-21 06:45:00    0.00   0.06   0.00     0.12       0.00    0.09    0.17
2026-08-21 07:15:00    0.01   0.07   0.01     0.13       0.02    0.10    0.18
                         ^^     ^^     ^^                          ^^
                      reset   −0.01  reset                       −0.01
```

The raw rows are already on the 5-minute grid, so nothing was resampled away.
At 06:45 the console **re-zeroed**: `1_hour` and `event` both went to exactly
`0.00`, `rain_rate` to `0.00`, while `daily` and `weekly` each lost **one
cent-inch and landed above zero**, and `monthly` and `yearly` held. A
**30-minute gap** follows — 06:45 → 07:15, the only non-5-minute step in the
whole day.

**Diagnosis, offered as this round's hypothesis and not as a measurement:** a
console restart or gauge re-zero, during which the two shortest-period
accumulators cleared and the two mid-period ones were recomputed a cent-inch
lower. What is *measured* is the table above; the cause is inferred from it and
the next round should treat it as something to test.

Either way, for the purposes of the stop condition it does not matter which
cause it was: **these are falls in true resetting accumulators that do not land
on zero, which is precisely what the check is for.** It earned its keep here.

## 2. The instrument was cross-checked before any of this was believed

`run_checks()` only publishes `odd_resets[:3]` in its note, so enumerating all
55 needed a replica of the loop — and a replica is a second copy that can
silently measure something else.

So **both were run on all 51 days**: the real `daily.run_checks()` for the
per-day verdict and count, and the replica for the entries. The replica was
trusted only where its count equalled the real check's.

```
days replayed         : 51
days with no data     : 0
A/B count mismatches  : 0
```

Zero mismatches across 51 days, so the enumeration above is the real check's
output and not a paraphrase of it.

## 3. `rainfall_piezo.event` — the side question, answered

The catalog says "resets per event" and the prompt notes nobody had checked.

**It is clean.** Over the 51 days `event` falls **9 times** and **every one
lands on zero** (0 landing above 0.001). It behaves exactly as the catalog
claims, and it is not implicated in any failing day.

## 4. What the proposed fix would have done — measured, not estimated

Step 3 asked for this number because it decides whether R-003 is still worth
building. It can be computed from the replay without touching code, so it is
reported despite the stop:

| day | irregular | breakdown | flips to PASS? |
|---|---|---|---|
| 2026-08-07 | 1 | `1_hour`×1 | ✅ |
| **2026-08-21** | **13** | `1_hour`×11, **`daily`×1, `weekly`×1** | ❌ **still FAILs** |
| 2026-08-24 | 5 | `1_hour`×5 | ✅ |
| 2026-08-25 | 11 | `1_hour`×11 | ✅ |
| 2026-08-26 | 3 | `1_hour`×3 | ✅ |
| 2026-09-10 | 6 | `1_hour`×6 | ✅ |
| 2026-09-11 | 2 | `1_hour`×2 | ✅ |
| 2026-09-12 | 6 | `1_hour`×6 | ✅ |
| 2026-09-20 | 8 | `1_hour`×8 | ✅ |

**9 days fail this check today. 8 would become PASS under a `1_hour`-only
exemption; 1 would still fail** — and the one that still fails is the only day
on which something genuinely went backwards.

That is the answer Step 3 wanted, and it is a strong one for R-003: this check
accounts for 9 noisy days, 8 of which are the metric mislabelling. It does not
measure how many of those 9 were *delivered* as ATTENTION emails, because that
depends on the other thirteen checks on the same day — that pairing is still
owed and needs `reporting.matrix`, which was not run because Step 3 sits behind
Step 2.

## 5. Two things Cowork's framing got slightly wrong

1. **"Two were R-002", of the five consecutive ATTENTION emails on 9–13 Sep.**
   This check FAILs on **9/10, 9/11 and 9/12** — three days in that window, not
   two. 9/11 is the day the register attributes to Rich moving the thermostat;
   both can be true of one email, and a day can fail two checks. Not a
   contradiction, but the count in the register row is one low, and if the
   ATTENTION volume is being used to size R-003 it should be the corrected one.
2. **9/9 and 9/13 were ATTENTION but this check PASSED on both.** Whatever made
   those two loud is something else entirely, and is not in any R-number yet.

## 6. What I did not do

- **Changed no code.** `git status` shows only `CLAUDE.md`, and that edit is
  Cowork's own bridge note about git locks, which was in the tree before this
  round began. Committed here per the protocol that note itself sets out.
- Did not touch `notebooks/ecowitt_daily.py`, `schema/metric_catalog_seed.sql`
  or `src/reporting/config.py`. No exemption set was added; the household-facing
  text at `config.py:286-289` still reads "A known quirk of the piezo gauge".
- Did not run `reporting.matrix`, did not render 12 Sep, and staged no breaks —
  all three belong to Steps 2 and 3.
- Closed the IAP tunnel this round opened on port 5434. Docker still holds 5433
  (`com.docke` pid 48557), exactly as R-001 found — `nb.ensure_db()` would still
  hand a caller the wrong database.

## 7. What the next round needs to decide

Not mine to choose, so it is stated as options rather than acted on:

- **Exempt `1_hour` only, and let 2026-08-21 keep failing.** Truest to the
  evidence — one real event stays visible, 8 noisy days go quiet.
- **Exempt `1_hour` and also stop flagging a fall that coincides with a console
  re-zero** (`event` → 0 in the same slot). Quieter, but it would have silenced
  the one genuine event in 51 days, and CLAUDE.md §14 requires a round that
  loosens a check to argue against the "a warning that is usually nothing"
  standard explicitly. This report does not make that argument.

---

**Start 2026-09-21 2:44 AM / End 2:53 AM : 08:14**

---

# Round 2 — the exemption, built to Cowork's decision

**Start 2026-09-21 3:00 AM.** Round 1's text above is unchanged.

Cowork's call: exempt `rainfall_piezo.1_hour` only; 21 August keeps failing.
Built as specified. The predicted numbers came out exactly as predicted, which
is itself worth one sentence of suspicion — so each was checked a second way.

## R2.1 The change

| What | Location | Before | After |
|---|---|---|---|
| The exemption | [ecowitt_daily.py:173](notebooks/ecowitt_daily.py#L173) | — | `ROLLING_NOT_ACCUMULATING = frozenset({'rainfall_piezo.1_hour'})` |
| The guard | [ecowitt_daily.py:385](notebooks/ecowitt_daily.py#L385) | — | `if metric in ROLLING_NOT_ACCUMULATING: continue` |
| Household text | [config.py:286](src/reporting/config.py#L286) | see below | see below |
| Fixture catalog | [conftest.py:42-47](tests/conftest.py#L42) | `daily` only | `+ weekly`, `+ 1_hour` |

The catalog was **not** touched, per the prompt. `kind` lives in the production
database as well as the seed and `metric_accumulator_needs_last` ties it to
`resample_rule`. **I do not think it should change.** The catalog's `kind` drives
resampling, where `last` is right for `1_hour` — it is a trailing total and the
last reading in a bucket is the correct one to keep. `kind` is only wrong for
*this one check's* purposes, so the narrow fix is also the honest one. No
migration is proposed.

### The household-facing text — Marc approves this in the close

**Before:**

> A rain total went backwards without resetting to zero. **A known quirk of the
> piezo gauge**; it affects rainfall figures only.

**After:**

> A rain total went backwards without resetting to zero, which a running total
> should not do. The day's rainfall figures may be understated; nothing else in
> the report is affected.

No cause is stated — the console re-zero is one observation, not a pattern.
Verified in the rendered 21 Aug email at line 25, so this is the text as three
people would actually receive it, not as the source file holds it.

## R2.2 What it changes, in numbers

`python -m reporting.matrix` over the whole record, before and after:

| | days | FAIL |
|---|---|---|
| before | 51 | **9** |
| after | 51 | **1** |

**8 flipped to PASS; 2026-08-21 still FAILs.** Matches the prompt's prediction.

⚠️ **The matrix's own column headers could not be parsed reliably** — the grid
wraps day-of-week and date onto separate lines, and a first attempt printed
nonsense like `Tue`/`12`/`Thu` as day labels. Rather than report those, the
surviving failure was named by re-running `run_checks` directly on the date:

```
2026-08-21: FAIL  measured='2 irregular'
   note: rainfall_piezo.daily at 06:45 -> 0.06; rainfall_piezo.weekly at 06:45 -> 0.09
```

Exactly 2 irregular, exactly the two metrics, exactly 06:45 — as required.

### 🚨 R2.3 The day-level outcome, which is the number R-003 needs

The prompt asked whether each flipped day's email is now *good*, or still
ATTENTION because of another check. **This is the finding of round 2, and it
substantially shrinks R-003.**

| day | this check | day-level verdict after | why |
|---|---|---|---|
| 2026-08-07 | FAIL → PASS | ✅ **GOOD** | nothing else was wrong |
| 2026-09-20 | FAIL → PASS | ✅ **GOOD** | nothing else was wrong |
| 2026-08-24 | FAIL → PASS | still FAIL | grid coverage; indoor within protection band |
| 2026-08-25 | FAIL → PASS | still FAIL | indoor climate holding; indoor within protection band |
| 2026-08-26 | FAIL → PASS | still FAIL | indoor within protection band |
| 2026-09-10 | FAIL → PASS | still WARN | indoor humidity in band |
| 2026-09-11 | FAIL → PASS | still FAIL | indoor climate holding; indoor humidity in band |
| 2026-09-12 | FAIL → PASS | still WARN | indoor humidity in band |
| 2026-08-21 | FAIL → **FAIL** | still FAIL | its own 2 entries, plus the house at 94.8 ºF |

**Only 2 of the 8 flipped days become quiet emails.** The other 6 were already
loud for **house** reasons — heat, humidity, the protection band — which are
exactly the failures that *should* be loud, and which R-003 was never about.

So this check was putting ATTENTION on a data-only basis on **2 days in 51**,
and R-002 removes both without R-003 existing. R-003's remaining value rests on
whatever *other* data-only checks do, which this round did not measure.

**Method stated, because the diagnosis depends on it:** the day-level verdict is
`daily._worst()` over every check in the frame, which is the same reduction the
report builds its severity from. The two rendered emails below are the
end-to-end confirmation that it agrees with the real subject line.

## R2.4 Both renders, dry run, nothing sent

| day | subject line |
|---|---|
| **2026-09-12** before | `… need ATTENTION … - 1 issue, **rain totals went backwards** …` |
| **2026-09-12** after | `REPLAY — Lake house Ecowitt System checks need ATTENTION for Sat, Sep 12th - 1 issue, indoor humidity 49–69 % — not current conditions` |
| **2026-08-21** after | `REPLAY — Lake house Ecowitt System checks need ATTENTION for Fri, Aug 21st - 2 issues, indoor 94.8 ºF — not current conditions` |

12 Sep now carries `[ok  ] rain accumulators only reset to zero: none` and reads
*"Working, with something worth a glance: indoor humidity in band."* The rain
sentence is gone from the subject line for the first time since 9 Sep.

21 Aug leads with the house at 94.8 ºF and keeps the rain failure below it —
which is the order `test_the_house_leads_when_several_checks_fail` already
pinned, still passing.

## 🚨 R2.5 Staged breaks — two, both red, with the tests named

**Fixtures are REAL data**, read off production on 2026-09-21 and recorded as
constants in the test module. The harness builds synthetic weather and could not
hold a whole real day, but these two series are the round, so they are the real
numbers rather than invented ones:

- `SEP12_1_HOUR_DECAY` — `1_hour`, 12 Sep 14:50–16:00
- `AUG21_DAILY` / `AUG21_WEEKLY` — 21 Aug 06:30–06:45

| break | test that went red | the red |
|---|---|---|
| exemption emptied | `test_a_rolling_hourly_total_decaying_is_not_an_irregular_reset` | `AssertionError: a rolling window decayed and the check called it irregular: rainfall_piezo.1_hour at 15:15 -> 0.08; 15:20 -> 0.06; 15:25 -> 0.05` · `assert 'FAIL' == 'PASS'` |
| exemption widened to `daily` | `test_a_real_backwards_step_in_a_true_accumulator_still_fails` | `AssertionError: expected both metrics flagged, got '1 irregular'` · `assert '1 irregular' == '2 irregular'` |

✅ **Break 1's message is the production email's own text**, verbatim — the same
`15:15 -> 0.08; 15:20 -> 0.06; 15:25 -> 0.05` the household received on 12 Sep.
That is the strongest evidence available that the fixture is the real failure
and not a lookalike.

🚨 **Break 2 caught something the obvious test would have missed.** Under it,
`assert row.verdict == "FAIL"` **still passed** — widening the exemption to
`daily` leaves `weekly` failing, so the day still fails, just for half the
reason. Only the count assertion went red. A guard written as "does 21 Aug still
fail" would have come back green while the exemption quietly swallowed a real
accumulator. The test asserts `measured == "2 irregular"` for exactly this
reason, and the break is what proved it was needed.

Both restored; `110 passed`; no `STAGED BREAK` string left in `src/`, `tests/`
or `notebooks/`.

## R2.6 Tests and lint

- **`110 passed`** (was 107). Three new, in `tests/test_reporting_report.py`,
  which is where this check was already tested.
- `ruff check .`: **16 errors, all in `notebooks/audit.ipynb`** — back to where
  it started.

⚠️ **An instrument caught, again, and again it was mine.** The first lint run
reported **18** errors while my filter said "none outside `audit.ipynb`". The
filter was wrong, not the count: it anchored on a pattern that does not match
ruff's default output format. Re-run with `--output-format=concise` and both new
errors were mine (E501, SIM300), both in the tests I had just written. Fixed,
and the count is back to 16. **The filter that said "clean" was the thing that
needed checking** — a count that moved while a filter said nothing moved should
never have been reported as clean.

## R2.7 One thing not asked for

`test_the_exemption_names_its_metric_rather_than_matching_a_pattern` pins the
set to exactly one member. It is a cheap guard against the failure mode the
comment warns about: `daily`, `weekly`, `monthly` and `yearly` are all "rain
over a period" names, and any prefix or suffix rule over `rainfall_piezo.*`
would swallow 21 August. Break 2 is what showed that swallowing one of them
leaves the day still failing and therefore still looking fine.

## R2.8 What I did not do

- Did not push and did not deploy. Committed locally only.
- Did not touch `schema/metric_catalog_seed.sql`, and propose no migration —
  reasoning in R2.1.
- Did not build R-003, only measured for it.
- Closed the tunnel on 5434. Docker still holds 5433 (R-006).

---

**Round 2 — Start 2026-09-21 3:00 AM / End 3:09 AM : 08:20**
