# Infrastructure

Decided 2026-08-02: **self-managed PostgreSQL 16 on a GCP `e2-micro` VM**,
`us-central1`, with the ingestion job running on the same box.

| file | purpose |
|---|---|
| [`create_vm.sh`](create_vm.sh) | provisions the VM, service account, backup bucket, firewall |
| [`vm_startup.sh`](vm_startup.sh) | runs on boot: swap, Postgres install, tuning, role + database |
| [`backup.sh`](backup.sh) | nightly dump → **verify** → upload → **verify again** |
| [`ecowitt-backup.service`](ecowitt-backup.service) / [`.timer`](ecowitt-backup.timer) | systemd units for the backup |

## Before running anything

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
./infra/create_vm.sh --dry-run     # review
./infra/create_vm.sh
```

Both scripts fail loudly on missing auth rather than proceeding.

## Cost — this is NOT free, despite the free tier

| item | monthly |
|---|---|
| `e2-micro` instance | **$0** — Always Free, 1 instance in us-central1/us-west1/us-east1 |
| 30 GB `pd-standard` disk | **$0** — Always Free |
| GCS backups (< 5 GB) | **$0** — Always Free, US regional |
| **External IPv4 address** | **~$3.65** — *not* covered by any free tier |
| **total** | **~$44/year** |

The IPv4 charge is unavoidable here: the VM needs outbound internet to reach
the Ecowitt API, and the no-external-IP alternative is Cloud NAT at roughly
$32/month. Assigning a *static* IP instead of ephemeral costs the same while
in use, and is worth it if anything ever needs a stable address.

**The free-tier constraints in `create_vm.sh` are load-bearing.** Changing the
machine type, using `pd-balanced`/`pd-ssd` instead of `pd-standard`, exceeding
30 GB, or moving outside the three eligible regions all start billing. The
script warns if you override them.

## What self-managing costs you

Choosing this over Cloud SQL traded ~$76/year against owning patching and
backups. That trade is only sound if the backups genuinely work, so
[`backup.sh`](backup.sh) does not merely dump and upload:

1. `pg_dump --format=custom`
2. **verifies** the archive by reading its table of contents and asserting the
   expected relations are present — `pg_dump` exiting 0 does not prove the
   archive is restorable
3. cross-checks the live `observation` row count against the archive contents
4. uploads to GCS
5. **re-reads the uploaded object's size** and compares — a successful `cp` is
   not proof the object landed intact
6. writes a `backup_log` heartbeat row

Any failure exits non-zero, which systemd records as a failed unit. §1 asks for
data "trustworthy without manual audit", and an unverified backup is exactly a
manual audit deferred until the day it fails.

**Do this before loading real data.** An unbacked-up database holding the only
full-resolution copy of a rolling 3-month window is the single biggest
liability of self-managing.

## Security posture

- Postgres listens on **localhost only**; there is deliberately no firewall
  rule for 5432
- The ingestion job connects over a **unix socket with peer authentication**,
  so there is no database password to store, rotate, or leak
- SSH only via **IAP tunnel** (`35.235.240.0/20`), not open to the internet
- The VM's service account has `secretAccessor` and `logWriter` only — no
  `roles/editor`
- Ecowitt API credentials live in **Secret Manager**, fetched at runtime

## Provisioned 2026-08-02

| resource | value |
|---|---|
| project | `ecowitt-504320` |
| instance | `ecowitt-db`, us-central1-a, e2-micro, 30 GB pd-standard |
| Postgres | 16.14 from PGDG (Debian 12 ships 15, so the repo is required) |
| database | `ecowitt`, owned by role `ecowitt`, peer auth over unix socket |
| backups | `gs://ecowitt-504320-ecowitt-backups`, 35-day lifecycle |
| SSH | IAP tunnel only (`35.235.240.0/20`) |

`schema/00_common.sql` is applied. All six constraints were verified to reject
their violations — see `schema/verify_constraints.sql`.

The curated table is **not** applied: the long-vs-wide decision is still open.

## Still open

**Monitoring.** The earlier "Cloud Run + Cloud Scheduler" decision is
superseded — with Postgres on this VM, running the job here too removes a VPC
connector, an egress path, and the database password. But it also removes the
external scheduler whose failures were visible in GCP. A systemd timer that
stops firing is silent, which is §10's primary risk. A heartbeat check against
`run_log` and `backup_log` is needed and is not built yet.
