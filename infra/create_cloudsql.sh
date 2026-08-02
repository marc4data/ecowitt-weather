#!/usr/bin/env bash
# Provision the Phase 1 Cloud SQL for PostgreSQL instance.
#
# Written as a script rather than console clicks so the choices are reviewable
# in git and the whole thing is repeatable. Safe to re-run: every step checks
# for existence first.
#
#   ./infra/create_cloudsql.sh --dry-run    # print what would happen
#   ./infra/create_cloudsql.sh
#
# Prerequisites you must do interactively (OAuth cannot run unattended):
#   gcloud auth login
#   gcloud config set project YOUR_PROJECT_ID
#
# NOTE ON COST: this creates a billable resource that charges monthly until
# deleted. See infra/README.md for the estimate.

set -euo pipefail

# --- settings -------------------------------------------------------------
PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-us-central1}"
INSTANCE="${INSTANCE:-ecowitt-weather}"
TIER="${TIER:-db-f1-micro}"
DB_VERSION="${DB_VERSION:-POSTGRES_16}"
DB_NAME="${DB_NAME:-ecowitt}"
DB_USER="${DB_USER:-ecowitt_app}"
STORAGE_SIZE="${STORAGE_SIZE:-10GB}"
BACKUP_START="${BACKUP_START:-08:00}"   # UTC
SECRET_NAME="${SECRET_NAME:-ecowitt-db-password}"

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

run() {
    if [[ $DRY_RUN -eq 1 ]]; then
        printf '  [dry-run] %s\n' "$*"
    else
        "$@"
    fi
}

say() { printf '\n==> %s\n' "$*"; }

# --- preflight ------------------------------------------------------------
if [[ -z "$PROJECT_ID" ]]; then
    echo "ERROR: no project set. Run: gcloud config set project YOUR_PROJECT_ID" >&2
    exit 2
fi
if ! gcloud auth list --filter=status:ACTIVE --format='value(account)' | grep -q .; then
    echo "ERROR: no active gcloud account. Run: gcloud auth login" >&2
    exit 2
fi

say "Project $PROJECT_ID · region $REGION · instance $INSTANCE · tier $TIER"

# --- APIs -----------------------------------------------------------------
say "Enabling required APIs (no-op if already enabled)"
run gcloud services enable \
    sqladmin.googleapis.com \
    secretmanager.googleapis.com \
    --project="$PROJECT_ID"

# --- instance -------------------------------------------------------------
if gcloud sql instances describe "$INSTANCE" --project="$PROJECT_ID" >/dev/null 2>&1; then
    say "Instance $INSTANCE already exists — skipping creation"
else
    say "Creating instance $INSTANCE (takes several minutes)"
    # Deliberate choices, each tied to a CLAUDE.md requirement:
    #   --backup + --enable-point-in-time-recovery : §8 point-in-time
    #     correctness. PITR keeps write-ahead logs so the database itself can
    #     be rewound, independently of the change_log audit trail.
    #   --deletion-protection : this holds the only full-resolution copy of a
    #     rolling 3-month window that cannot be re-fetched once lost (§6).
    #   --storage-auto-increase : a full disk is a silently dead job (§10).
    #   no --authorized-networks : the instance gets a public IP but accepts
    #     nothing directly. Connections come through the Cloud SQL connector
    #     with IAM, so there is no open port to the internet.
    run gcloud sql instances create "$INSTANCE" \
        --project="$PROJECT_ID" \
        --region="$REGION" \
        --database-version="$DB_VERSION" \
        --tier="$TIER" \
        --storage-size="$STORAGE_SIZE" \
        --storage-type=SSD \
        --storage-auto-increase \
        --availability-type=zonal \
        --backup \
        --backup-start-time="$BACKUP_START" \
        --enable-point-in-time-recovery \
        --retained-transaction-log-days=7 \
        --maintenance-window-day=SUN \
        --maintenance-window-hour=9 \
        --deletion-protection
fi

# --- database -------------------------------------------------------------
if gcloud sql databases describe "$DB_NAME" --instance="$INSTANCE" \
        --project="$PROJECT_ID" >/dev/null 2>&1; then
    say "Database $DB_NAME already exists — skipping"
else
    say "Creating database $DB_NAME"
    run gcloud sql databases create "$DB_NAME" \
        --instance="$INSTANCE" --project="$PROJECT_ID"
fi

# --- application user + secret --------------------------------------------
# §10: secrets never enter the repo. The password is generated here, written
# straight to Secret Manager, and never echoed or persisted locally.
if gcloud secrets describe "$SECRET_NAME" --project="$PROJECT_ID" >/dev/null 2>&1; then
    say "Secret $SECRET_NAME already exists — leaving the existing password alone"
else
    say "Generating application password and storing it in Secret Manager"
    if [[ $DRY_RUN -eq 1 ]]; then
        echo "  [dry-run] generate password, create secret $SECRET_NAME, create user $DB_USER"
    else
        DB_PASSWORD="$(openssl rand -base64 32)"

        printf '%s' "$DB_PASSWORD" | gcloud secrets create "$SECRET_NAME" \
            --project="$PROJECT_ID" --replication-policy=automatic --data-file=-

        # --prompt-for-password would be safer still, but cannot be scripted.
        # This puts the password in this process's argv briefly; acceptable on
        # a single-user workstation, and it is rotated out by moving to IAM
        # database authentication (see infra/README.md).
        gcloud sql users create "$DB_USER" \
            --instance="$INSTANCE" --project="$PROJECT_ID" \
            --password="$DB_PASSWORD"

        unset DB_PASSWORD
    fi
fi

say "Done."
cat <<EOF

Connection name:
  $(gcloud sql instances describe "$INSTANCE" --project="$PROJECT_ID" \
      --format='value(connectionName)' 2>/dev/null || echo '(instance not created yet)')

Next:
  1. Apply the schema:
       gcloud sql connect $INSTANCE --user=$DB_USER --database=$DB_NAME
       \\i schema/00_common.sql
       \\i schema/option_a_long.sql        # or option_b_wide.sql
  2. Grant the Cloud Run service account access to $SECRET_NAME.

The password is only in Secret Manager. Retrieve with:
  gcloud secrets versions access latest --secret=$SECRET_NAME
EOF
