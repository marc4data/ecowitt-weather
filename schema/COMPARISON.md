# Table shape — the same five operations, in both schemas

You asked to decide from DDL rather than prose. Both schemas are written to be
genuinely usable; Option B is not a strawman. Files:

- [`00_common.sql`](00_common.sql) — shared by both: `run_log`, `raw_payload`,
  `metric_catalog`, `change_log`, `quarantine`
- [`option_a_long.sql`](option_a_long.sql) — long store, wide view
- [`option_b_wide.sql`](option_b_wide.sql) — wide store, long view

**Neither has been executed.** No Postgres instance exists yet. Both are
parse-checked as PostgreSQL by `tests/test_schema.py`, which validates syntax
only — it cannot catch a semantic error, and it does not meaningfully check the
plpgsql immutability trigger. Run them against a scratch database before
trusting them.

---

## 1. Idempotent load with change detection (§7, §10)

**A — one statement, and "unchanged" falls out of it.**

```sql
ON CONFLICT (station_id, ts_utc, metric) DO UPDATE
    SET value_text = EXCLUDED.value_text, ...
    WHERE o.value_text IS DISTINCT FROM EXCLUDED.value_text
       OR o.unit       IS DISTINCT FROM EXCLUDED.unit
RETURNING (xmax = 0) AS was_insert;
```

Conflicting rows that fail the `WHERE` return nothing — those are the unchanged
ones. `run_log`'s inserted/updated/unchanged counters come straight from the
statement.

**B — the same idea, written 42 times.** Every column appears in the `SET`, and
again in the `WHERE`, and the two must stay in sync forever. Worse, `RETURNING`
gives you the whole row but not *which field* changed, so `change_log` rows have
to be produced by diffing in application code.

> §7 says "Never issue a blind upsert" and "unchanged must be a countable
> outcome." A gets both structurally. B gets them by discipline.

## 2. Adding a sensor

You have 2 of 16 soil channels and 3 of 8 T/RH channels connected.

**A** — two `INSERT`s into `metric_catalog`. No `ALTER`, no downtime, no
redeploy.

**B** — `ALTER TABLE` on the table holding your training data, plus edits to the
upsert, the `WHERE`, the change-detection diff, `observation_long`, and every
downstream view. Rows written before the `ALTER` carry `NULL`, which is
indistinguishable from "sensor present but silent."

## 3. Units (§10 — "record the unit each value arrived in")

Units are per-metric, not per-row: `outdoor.vpd` is `inHg` while
`outdoor.temperature` is `ºF`.

**A** — a column on the row. Done.

**B** — three options, all bad: 42 parallel `*_unit` columns (84 columns, nearly
all constant), one unit set per row (loses fidelity), or a metric-keyed side
table. B uses the side table — **which means the wide design needs a
metric-keyed table anyway.**

## 4. Unparseable values (§10 — "no unconditional casts")

**A** — `value_text` holds exact bytes, `value_num` holds the parsed form or
`NULL`. A value that fails to parse is a recorded fact.

**B** — only the typed column exists. An unparseable value can only be `NULL`,
indistinguishable from "sensor reported nothing." The raw JSON is still in
`raw_payload`, so nothing is lost permanently — but recovery means re-reading
raw payloads instead of reading the curated row.

## 5. Point-in-time reconstruction (§8)

**A** — a `WHERE` clause. `change_log`'s natural key *is* the observation
table's primary key `(station_id, ts_utc, metric)`, so the join is direct.

**B** — `change_log` is field-level by §7's definition, so it stays keyed by
metric while the table is keyed by timestamp. Every reconstruction crosses that
mismatch.

---

## Where B genuinely wins

Not nothing:

- **Feature matrices are free.** `SELECT * FROM observation_wide` is the Phase 4
  shape, with no pivot.
- **Rows are dense, not sparse.** All 39 history metrics share one identical
  281-timestamp set (D3), so a wide row has no ragged edges. This is the usual
  argument against wide, and it does not apply here.
- **Fewer rows** — 288/day versus ~12k/day. Both are trivial at this scale
  (~4.4M rows/year for A).
- **Simpler to eyeball** in a SQL console.

## Recommendation

**Option A.** The deciding factor is not query convenience — B wins that — but
that `change_log` is *already* field-level in §7, so A's primary key and the
audit trail's natural key are the same tuple. Every §7 and §8 requirement is
then a property of the schema rather than a rule the application must remember.

B's advantages are all recoverable as views. A's advantages are not recoverable
by a wide table.

The honest cost of A: a pivot sits between you and a feature matrix, and
`observation_wide` has to be regenerated when metrics are added. That is a
generated view, not a migration.

## Open question either way

`metric_catalog` must be populated before any observation row can be inserted
(the FK enforces it). The classifications come from
[`../samples/reports/metric_catalog.md`](../samples/reports/metric_catalog.md)
and encode four rules as `CHECK` constraints — circular metrics must use
`vector_mean`, extrema must use `max`, accumulators must use `last`, and
`status`/`opaque` metrics cannot be marked resamplable.
