# Table shape on BigQuery — the same operations, both schemas

Files: [`00_common.sql`](00_common.sql) (shared), [`assertions.sql`](assertions.sql)
(**required on every load**), [`option_a_long.sql`](option_a_long.sql),
[`option_b_wide.sql`](option_b_wide.sql).

**Nothing here has been executed.** No dataset exists yet. `tests/test_schema.py`
parse-checks all four as BigQuery — syntax only. It cannot catch a semantic
error and it cannot tell you whether an `ASSERT` holds.

---

## First: the platform change moved this decision

The Postgres draft (commit `23054c2`) recommended long, and two of its three
strongest arguments **do not survive the move to BigQuery**:

| argument for long, on Postgres | on BigQuery |
|---|---|
| Adding a sensor means a migration on a table holding training data | ❌ **Gone.** `ALTER TABLE ADD COLUMN` is a free metadata operation — instant, no rewrite, no downtime |
| A `FOREIGN KEY` guarantees every metric is classified | ❌ **Gone.** FKs are `NOT ENFORCED`; both options rely on an assertion instead |
| Sparse/unused columns waste space | ❌ **Gone.** Columnar storage means unused columns cost nothing to store or scan |

And wide gained arguments it did not have on Postgres:

- **42× fewer rows** — 105k/year vs 4.4M/year. `MERGE` touches 288 rows/day
  instead of 12k.
- **~13× less storage** — long repeats `station_id` and `metric` on every row
  (~495 MB/yr vs ~37 MB/yr). Both are free-tier trivial, but it is real.
- **Feature matrices are a plain `SELECT`**, which matters for Phase 4 and for
  BigQuery ML.

This is now a close decision. It was not close on Postgres.

## What still favours long

**1. `change_log` is field-level, and long's row identity matches it.**

§7 defines the audit trail as `natural key · field · old · new`. Option A's row
*is* that tuple, so emitting `change_log` falls out of the same comparison that
drives the `MERGE`. Option B has to answer "which of 42 columns changed" with
either 42 `UNION ALL` branches or an application-side diff.

This is the one argument the platform change did not touch, and §7 and §8 are
the project's instrumentation backbone.

**2. Units are per-metric, so wide needs a metric-keyed table anyway.**

`outdoor_vpd` is `inHg` while `outdoor_temperature` is `ºF`. Option B ends up
with `observation_wide_units` — a long table by another name.

**3. `value_text` preservation.**

Option A stores exact returned bytes beside the parsed number, so an
unparseable value is a *recorded fact*. Option B would need 42 more `STRING`
columns; without them, a parse failure is `NULL` — indistinguishable from "the
sensor said nothing". That ambiguity is exactly what §10's no-unconditional-casts
rule exists to prevent.

**4. Adding a sensor is still zero-code in A.** The `ALTER` is free in B, but
the `MERGE` `SET` list, the `MERGE` `WHERE` list, the change-detection diff,
`observation_long`, and every downstream view all change by hand.

## The option I considered and am not recommending

BigQuery's idiomatic answer is neither: **one row per `(station, ts_utc)` with
metrics as `ARRAY<STRUCT<metric, value_text, value_num, unit, source>>`.** It
gets wide's row count, long's tolerance of new sensors, per-metric units, and
`value_text` — all at once, and `UNNEST` gives you the long view for free.

I am not recommending it because updating one metric means rewriting the whole
row's array, and reconstructing that array while preserving metrics *not* in the
current pull is fiddly array manipulation. It makes §7's change detection — the
thing this project cares most about — the hardest part of the design rather
than the easiest. Worth revisiting if `MERGE` cost ever becomes real, which at
this volume it will not.

## Recommendation

**Still Option A, but on a narrower margin than on Postgres.**

The deciding factor is now singular rather than cumulative: `change_log` is
field-level by §7's own definition, so in A the curated table's key and the
audit trail's key are the same tuple, and change detection is free. Everything
else has equalised or flipped toward B.

If you weight Phase 4 convenience over Phase 1 instrumentation, B is a
defensible choice on BigQuery in a way it was not on Postgres. I would not
argue hard against it.

## What both options now depend on

`assertions.sql` is not optional. On Postgres, five of `CLAUDE.md`'s rules were
enforced by the database — an unredacted credential, a mutated raw payload, a
duplicate observation, an unclassified metric, and a violated resampling rule
were all *impossible*. On BigQuery each is merely *detectable*.

Wire the assertions into the Cloud Run job so a failure marks the run `failed`
and exits non-zero. An assertion suite that runs but is ignored is worse than
none, because it looks like coverage.
