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
