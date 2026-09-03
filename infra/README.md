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

## Querying the database from a GUI

Postgres listens on localhost only, so a GUI needs an SSH tunnel. There is no
open database port and this does not add one.

```bash
./infra/tunnel.sh            # opens it, waits until it truly accepts connections
./infra/tunnel.sh --check    # is it up?
```

Use [`tunnel.sh`](tunnel.sh) rather than the raw gcloud command. Run on the VM
or in Cloud Shell, the raw command fails with an opaque IAM error — *Required
'compute.instances.get' permission* — which says nothing about the actual
problem, namely that you are not on your workstation. The shell prompt looks
identical in all three places. The script refuses to run anywhere but a
workstation and says why, and it waits for the port to genuinely accept a
connection rather than returning the instant `ssh` forks: "the command didn't
error" and "pgAdmin can connect" are not the same thing.

Telling the machines apart by hand:

| | workstation | VM |
|---|---|---|
| hostname | `Marcs-MacBook-Pro.local` | `ecowitt-db` |
| home | `/Users/marcalexander` | `/home/marcalexander` |
| gcloud identity | the operator’s address | `ecowitt-vm@…gserviceaccount.com` |

On the VM no tunnel is needed at all — `sudo -u ecowitt psql ecowitt`.

pgAdmin / DBeaver: `localhost:5433`, database `ecowitt`, user `ecowitt_ro`.

Created by [`create_readonly_user.sh`](create_readonly_user.sh). A **separate,
read-only** role rather than a password on `ecowitt` — the ingestion job uses
peer auth over a unix socket and has no password at all, and adding one for a
GUI's convenience would throw that away. Read-only because `raw_payload`'s
append-only trigger only fires on UPDATE/DELETE; a write-capable role could
still corrupt `observation` or `change_log` with a mistyped statement, and §8
requires corrections to be recorded as changes rather than in-place overwrites.

Enforced twice — SELECT-only grants plus `default_transaction_read_only`.
Verified: DELETE, UPDATE, INSERT, DROP, CREATE, and mutating `raw_payload` are
all refused, and the row count is unchanged afterwards.

The password is generated locally, pushed straight to Secret Manager, and
fetched by the VM's own service account — it never appears in a command line,
a process list, or on disk.

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

Applied: `00_common.sql`, `option_a_long.sql` (long/tall chosen 2026-08-02),
`metric_catalog_seed.sql` (42 metrics). All constraints verified to reject
their violations — see `schema/verify_constraints.sql`.

Four timers installed and exercised against the live database:

| timer | schedule | purpose |
|---|---|---|
| `ecowitt-ingest` | hourly | incremental pull, last 4 h |
| `ecowitt-reconcile` | 10:00 UTC | previous 24 h in 2 × 12 h chunks |
| `ecowitt-backup` | 09:00 UTC | dump → verify → upload → verify |
| `ecowitt-heartbeat` | every 15 min | staleness + dead-man's switch |

Reconcile runs *after* the backup so a run that rewrites values is captured by
the next backup rather than racing the current one.

Ecowitt credentials live in Secret Manager (`ecowitt-application-key`,
`ecowitt-api-key`, `ecowitt-mac`), fetched at runtime by `run_ingest.sh` into
the process environment. They never touch disk on the VM.

## Monitoring — two silences, two policies

Colocating the job removed Cloud Scheduler, whose failures were visible in the
console. A systemd timer that stops firing is silent, and §10 calls that the
project's primary risk. Two failure modes need two mechanisms:

| failure | mechanism | policy |
|---|---|---|
| Box alive, data stale | `heartbeat.sh` emits an ERROR log entry | *pipeline reporting unhealthy* |
| Box dead, timer stopped, Postgres gone | **nothing is emitted at all** | *pipeline is not reporting* — fires on metric **absence** |

The second is the one that matters and the one an error-only alert would miss:
a dead machine produces no errors, just silence and a green dashboard. So the
heartbeat emits on **every** run, healthy or not, and the absence of those
entries is itself the alarm — the same argument §7 makes for `run_log`.

Set up with [`create_monitoring.sh`](create_monitoring.sh). It uses the
Monitoring REST API rather than `gcloud alpha/beta monitoring`, because those
component groups are not installed and `gcloud components install` is disabled
on a Homebrew-managed CLI — depending on them would mean either a broken script
or modifying the operator's toolchain.

**Verify the dead-man's switch rather than trusting it:**

```bash
gcloud compute ssh ecowitt-db --zone=us-central1-a --tunnel-through-iap \
  --command='sudo systemctl stop ecowitt-heartbeat.timer'
# expect an email in ~1h, then start it again
```

Alerts go to the operator’s address. **Confirm the subscription in your inbox** —
an unconfirmed channel silently delivers nothing.

### The daily email is watched by the same switch

`ecowitt-report.timer` sends the household email each morning
([01_DAILY_EMAIL_REQUIREMENTS.md](../01_DAILY_EMAIL_REQUIREMENTS.md)). It gets no
new alerting infrastructure — a successful send writes an `email_log` row, and
`heartbeat.sh` grew a sixth query for the age of the newest **production** row
(`MAX_EMAIL_AGE_MIN`, 26 h). A stalled emailer then trips *pipeline reporting
unhealthy*, and a dead box still trips *pipeline is not reporting*.

⚠️ **The `mode = 'production'` filter in that query is the whole point.** Without
it a `--test` send at 3pm resets the clock and masks a production email that
never went out — an observability check defeated by the act of testing it.

Verify it the same way as the others, by breaking it:

```bash
sudo systemctl stop ecowitt-report.timer     # then wait out 26h
sudo -u ecowitt /opt/ecowitt/app/run_report.sh --test   # must NOT clear the alarm
```

The outermost layer is not on the VM at all: every email's footer tells three
people when it should arrive. Three people noticing that the morning email did
not come is a cheaper and more reliable detector than anything running here.

## Turning on the daily email

Four scripts, in this order. Each one refuses to run if the one before it has
not been done, so a wrong order is a clear error rather than a broken box.

Everything runs **from the repo root on your workstation**. `gcloud` is a client
for Google's API — it talks to GCP from your laptop. You never need to log into
the VM by hand; the scripts do that over IAP where something has to happen on
the machine itself.

```bash
# 1. email_log + the one role allowed to write it  (~1 min)
./infra/create_emailer_user.sh

# 2. the secrets: Gmail app password, and optionally the Anthropic key
#    and contacts. Prompts for each; nothing lands in shell history.   (~2 min)
./infra/create_report_secrets.sh

# 3. install, verify, and turn it on                        (~5-10 min: the
#    pandas/matplotlib build on a 1 GB e2-micro is the slow part)
LAKEHOUSE_EMAIL_TO='marc@…,stacy@…,tad@…' \
LAKEHOUSE_EMAIL_TEST_TO='marc@…' \
LAKEHOUSE_EMAIL_FROM='marc@…' \
LAKEHOUSE_STATION_URL='https://www.ecowitt.net/home/index?id=…' \
./infra/deploy_report.sh
```

`deploy_report.sh` installs with the timer **off**, sends one `--test` email from
the VM, and enables the timer only if that email actually went out. A scheduler
enabled for something that has never run is a promise nobody has checked, and
the first unattended run would be 07:00 on the morning it matters.

### What each piece needs, and why it is where it is

| Value | Lives in | Why there |
|---|---|---|
| database passwords, Gmail app password, Anthropic key, contacts | **Secret Manager** | secrets, and personal data. Fetched at runtime by the VM's own service account; never written to disk |
| email addresses, station URL, workspace id | **the unit file** | not secrets. A reviewer should see who this machine emails without opening a secret store |
| check thresholds | `notebooks/ecowitt_daily.py` | one copy, shared with the notebook, so the two can never disagree |

### Then verify the two things a green install does not prove

```bash
# The ACTION path — it only ever runs on a bad morning, so it is the least
# exercised code in the system. This sends a synthetic one to the test address.
gcloud compute ssh ecowitt-db --zone=us-central1-a --tunnel-through-iap \
  --command="sudo -u ecowitt LAKEHOUSE_EMAIL_TO=x LAKEHOUSE_EMAIL_TEST_TO=you@x \
             LAKEHOUSE_EMAIL_FROM=you@x /opt/ecowitt/app/run_report.sh --selftest --test"

# The dead-man's switch, by breaking it (see "Monitoring" above)
sudo systemctl stop ecowitt-report.timer    # wait out 26 h, confirm the alert
```

### Rolling back

```bash
sudo systemctl disable --now ecowitt-report.timer
```

Nothing else needs undoing. The ingestion job, the backups and the heartbeat are
independent of the report — the only thing the report added to them is the sixth
heartbeat query, which stays quiet until a production email has been sent once.

## Still open
