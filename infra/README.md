# Infrastructure

Decided 2026-08-02: **BigQuery** (dataset location `us-central1`), with the
Phase 1 job running as a **Cloud Run job on Cloud Scheduler**.

Provisioning lives in [`create_bigquery.sh`](create_bigquery.sh) rather than in
console clicks, so the choices are reviewable in git. Safe to re-run; supports
`--dry-run`.

## Before running it

`gcloud` OAuth cannot run unattended, so these are yours:

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
```

The preflight fails loudly if either is missing rather than proceeding.

## Cost

Effectively **$0/month** at this volume, and it stays there for years:

| | usage | free tier | cost |
|---|---|---|---|
| Storage | ~0.5 GB/yr long, ~37 MB/yr wide | 10 GiB/month | $0 |
| Queries | full scan ≈ 0.5 GB | 1 TiB/month | $0 |
| Batch loads | free operation | — | $0 |

Beyond the free tier it is $6.25/TiB scanned and $23.55/TiB/month active
storage. Reaching either would take roughly 2,000 full-table scans a month or
20 years of accumulation.

**The one way this design could cost money** is an unpartitioned scan. Both
curated tables set `require_partition_filter = TRUE`, and the `MERGE` carries an
explicit `DATE(...) BETWEEN` predicate, so a query that would scan every
partition fails instead of silently billing.

## What BigQuery does not give us

This was a deliberate trade — ~$0/month in exchange for losing the enforcement
layer. On Postgres (commit `23054c2`) five `CLAUDE.md` rules were *impossible*
to violate; here they are merely *detectable*:

| rule | Postgres | BigQuery |
|---|---|---|
| raw payload immutable | trigger that RAISEs | convention + digest check |
| no unredacted credential | `CHECK` | assertion query |
| idempotent load | enforced `PRIMARY KEY` | `NOT ENFORCED` PK + `MERGE` |
| every metric classified | `FOREIGN KEY` | assertion query |
| resampling traps | `CHECK` | assertion query |

[`../schema/assertions.sql`](../schema/assertions.sql) carries that burden and
**must run on every load**, with a failure marking the run `failed` and exiting
non-zero. An assertion suite that runs but is ignored is worse than none.

Note also that BigQuery IAM has no insert-without-delete role — `dataEditor`
grants both — so append-only really is a convention, not a permission boundary.
7-day time travel is the recovery path if it is violated.

## Not yet provisioned

The Cloud Run job, Cloud Scheduler trigger, service account, and IAM bindings
are not scripted yet. They depend on the Phase 1 job existing and on the table
shape being chosen.
