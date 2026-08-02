#!/usr/bin/env bash
# Provision the e2-micro VM that runs PostgreSQL and the ingestion job.
#
#   ./infra/create_vm.sh --dry-run
#   ./infra/create_vm.sh
#
# Prerequisites (OAuth cannot run unattended, so these are yours):
#   gcloud auth login
#   gcloud config set project YOUR_PROJECT_ID
#
# COST: the instance and its 30 GB standard disk are within GCP's Always Free
# tier. The external IPv4 address is NOT -- it is roughly $3.65/month. See
# infra/README.md. Every free-tier constraint below is load-bearing; changing
# the machine type, disk type, or region will start billing.

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
ZONE="${ZONE:-us-central1-a}"          # free tier: us-central1|us-west1|us-east1
INSTANCE="${INSTANCE:-ecowitt-db}"
MACHINE="${MACHINE:-e2-micro}"          # free tier: e2-micro only
DISK_SIZE="${DISK_SIZE:-30GB}"          # free tier: up to 30 GB
DISK_TYPE="${DISK_TYPE:-pd-standard}"   # free tier: standard ONLY, not balanced/SSD
IMAGE_FAMILY="${IMAGE_FAMILY:-debian-12}"
SA_NAME="${SA_NAME:-ecowitt-vm}"
BACKUP_BUCKET="${BACKUP_BUCKET:-${PROJECT_ID}-ecowitt-backups}"

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1
say() { printf '\n==> %s\n' "$*"; }
run() { if [[ $DRY_RUN -eq 1 ]]; then printf '  [dry-run] %s\n' "$*"; else "$@"; fi; }

# --- preflight ------------------------------------------------------------
[[ -n "$PROJECT_ID" ]] || { echo "ERROR: no project set. gcloud config set project ..." >&2; exit 2; }
gcloud auth list --filter=status:ACTIVE --format='value(account)' | grep -q . \
    || { echo "ERROR: no active gcloud account. gcloud auth login" >&2; exit 2; }
[[ -f infra/vm_startup.sh ]] || { echo "ERROR: run from the repo root" >&2; exit 2; }

if [[ "$MACHINE" != "e2-micro" || "$DISK_TYPE" != "pd-standard" ]]; then
    echo "WARNING: $MACHINE/$DISK_TYPE is outside the Always Free tier — this will bill." >&2
fi

say "Project $PROJECT_ID · zone $ZONE · $INSTANCE ($MACHINE, $DISK_SIZE $DISK_TYPE)"

say "Enabling APIs"
run gcloud services enable compute.googleapis.com secretmanager.googleapis.com \
    iap.googleapis.com --project="$PROJECT_ID"

# --- service account ------------------------------------------------------
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
if gcloud iam service-accounts describe "$SA_EMAIL" --project="$PROJECT_ID" >/dev/null 2>&1; then
    say "Service account $SA_NAME exists"
else
    say "Creating service account $SA_NAME"
    run gcloud iam service-accounts create "$SA_NAME" \
        --project="$PROJECT_ID" --display-name="Ecowitt ingestion VM"
fi

# Least privilege: read the Ecowitt API credentials, write backups, write logs.
# Deliberately no roles/editor.
say "Granting minimal roles"
for role in roles/secretmanager.secretAccessor roles/logging.logWriter; do
    run gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="serviceAccount:$SA_EMAIL" --role="$role" --condition=None --quiet
done

# --- backup bucket --------------------------------------------------------
if gcloud storage buckets describe "gs://$BACKUP_BUCKET" --project="$PROJECT_ID" >/dev/null 2>&1; then
    say "Backup bucket exists: gs://$BACKUP_BUCKET"
else
    say "Creating backup bucket gs://$BACKUP_BUCKET"
    # US regional storage: 5 GB-months is Always Free. Versioning off; the
    # lifecycle rule below is the retention policy.
    run gcloud storage buckets create "gs://$BACKUP_BUCKET" \
        --project="$PROJECT_ID" --location=us-central1 \
        --uniform-bucket-level-access
fi
say "Applying 35-day backup retention"
if [[ $DRY_RUN -eq 1 ]]; then
    echo "  [dry-run] set lifecycle: delete objects older than 35 days"
else
    tmp="$(mktemp)"
    cat > "$tmp" <<'JSON'
{"rule":[{"action":{"type":"Delete"},"condition":{"age":35}}]}
JSON
    gcloud storage buckets update "gs://$BACKUP_BUCKET" --lifecycle-file="$tmp"
    rm -f "$tmp"
fi
run gcloud storage buckets add-iam-policy-binding "gs://$BACKUP_BUCKET" \
    --member="serviceAccount:$SA_EMAIL" --role=roles/storage.objectAdmin

# --- firewall -------------------------------------------------------------
# SSH only via IAP (35.235.240.0/20). Postgres listens on localhost and is
# never exposed, so there is deliberately no rule for 5432.
if gcloud compute firewall-rules describe allow-iap-ssh --project="$PROJECT_ID" >/dev/null 2>&1; then
    say "Firewall rule allow-iap-ssh exists"
else
    say "Creating IAP-only SSH firewall rule"
    run gcloud compute firewall-rules create allow-iap-ssh \
        --project="$PROJECT_ID" --direction=INGRESS --action=allow \
        --rules=tcp:22 --source-ranges=35.235.240.0/20 \
        --description="SSH via IAP tunnel only"
fi

# --- instance -------------------------------------------------------------
if gcloud compute instances describe "$INSTANCE" --zone="$ZONE" \
        --project="$PROJECT_ID" >/dev/null 2>&1; then
    say "Instance $INSTANCE already exists — skipping creation"
else
    say "Creating $INSTANCE"
    run gcloud compute instances create "$INSTANCE" \
        --project="$PROJECT_ID" --zone="$ZONE" \
        --machine-type="$MACHINE" \
        --image-family="$IMAGE_FAMILY" --image-project=debian-cloud \
        --boot-disk-size="$DISK_SIZE" --boot-disk-type="$DISK_TYPE" \
        --network-tier=STANDARD \
        --service-account="$SA_EMAIL" \
        --scopes=https://www.googleapis.com/auth/cloud-platform \
        --metadata-from-file=startup-script=infra/vm_startup.sh \
        --labels=project=ecowitt,phase=1 \
        --deletion-protection
fi

say "Done."
cat <<EOF

Instance: $INSTANCE ($ZONE)
Backups:  gs://$BACKUP_BUCKET  (35-day retention)

Next:
  1. Watch the startup script finish (installs Postgres, ~2 min):
       gcloud compute ssh $INSTANCE --zone=$ZONE --tunnel-through-iap \\
         --command='sudo tail -f /var/log/ecowitt-startup.log'
  2. Copy the schema up and apply it — a reviewed, one-time step:
       gcloud compute scp --recurse schema $INSTANCE:/tmp/ --zone=$ZONE --tunnel-through-iap
       gcloud compute ssh $INSTANCE --zone=$ZONE --tunnel-through-iap
       sudo -u ecowitt psql ecowitt -f /tmp/schema/00_common.sql
       sudo -u ecowitt psql ecowitt -f /tmp/schema/option_a_long.sql
  3. Install infra/backup.sh and its systemd timer. Do this BEFORE loading
     real data — an unbacked-up database holding irreplaceable 5-minute data
     is the single biggest liability of self-managing.

COST REMINDER: instance + 30 GB standard disk are Always Free; the external
IPv4 is ~\$3.65/month. Verify with:
  gcloud billing accounts list
EOF
