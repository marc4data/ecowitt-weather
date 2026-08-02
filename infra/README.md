# Infrastructure

Target, decided 2026-08-02: **Cloud SQL for PostgreSQL**, with the Phase 1 job
running as a **Cloud Run job on Cloud Scheduler**.

Provisioning lives in [`create_cloudsql.sh`](create_cloudsql.sh) rather than in
console clicks, so the choices are reviewable in git and the setup is
repeatable. The script is safe to re-run — every step checks for existence
first — and supports `--dry-run`.

## Before running it

`gcloud` OAuth cannot run unattended, so these two are yours:

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
```

The project also needs billing enabled. The script's preflight fails loudly if
either is missing rather than proceeding.

## Cost

**This creates a billable resource that charges monthly until deleted.**
Rough us-central1 figures — confirm against current pricing, these move:

| tier | RAM | ~monthly | notes |
|---|---|---|---|
| `db-f1-micro` | 0.6 GB | ~$8–10 | shared core, **no SLA** |
| `db-g1-small` | 1.7 GB | ~$25–30 | shared core, no SLA |
| `db-custom-1-3840` | 3.75 GB | ~$50+ | dedicated vCPU, SLA-covered |

Plus ~$1.70/mo per 10 GB SSD, plus PITR write-ahead log storage.

At ~4.4M rows/year the workload is tiny; `db-f1-micro` is sufficient on
capacity. The honest tension is that shared-core tiers carry no SLA, and this
project's stated primary risk is a silently dead job (§10). Tiers can be
changed later with a restart and no data loss, so starting small is reversible.

## Choices baked into the script, and why

| flag | reason |
|---|---|
| `--backup`, `--enable-point-in-time-recovery` | §8 point-in-time correctness — lets the database itself be rewound, independently of the `change_log` audit trail |
| `--deletion-protection` | this holds the only full-resolution copy of a rolling 3-month window that **cannot be re-fetched once lost** (§6) |
| `--storage-auto-increase` | a full disk is a silently dead job (§10) |
| `--availability-type=zonal` | HA roughly doubles cost; a batch job that retries tolerates a zonal restart |
| no `--authorized-networks` | the instance takes a public IP but accepts nothing directly; connections come via the Cloud SQL connector with IAM, so no open port |

## Secrets

§10: secrets never enter the repo. The application password is generated inside
the script, written straight to Secret Manager, and never echoed or written to
disk. Retrieve it with:

```bash
gcloud secrets versions access latest --secret=ecowitt-db-password
```

**Known weakness:** `gcloud sql users create --password=` puts the password in
that process's argv briefly. `--prompt-for-password` is safer but cannot be
scripted. The proper fix is IAM database authentication for the Cloud Run
service account, which removes the application password entirely — worth doing
before the job goes unattended, and it makes this exposure moot.

## Not yet provisioned

The Cloud Run job, Cloud Scheduler trigger, service account, and IAM bindings
are not scripted yet. They depend on the Phase 1 job existing and on the table
shape being chosen.
