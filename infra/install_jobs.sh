#!/usr/bin/env bash
# Install the backup and heartbeat units on the VM. Run FROM the repo root on
# your workstation; it copies to the VM over IAP and enables the timers.
#
#   ./infra/install_jobs.sh
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
ZONE="${ZONE:-us-central1-a}"
INSTANCE="${INSTANCE:-ecowitt-db}"
BACKUP_BUCKET="${BACKUP_BUCKET:-${PROJECT_ID}-ecowitt-backups}"
SSH=(gcloud compute ssh "$INSTANCE" --zone="$ZONE" --tunnel-through-iap --quiet)

echo "==> Staging files to $INSTANCE"
gcloud compute scp infra/backup.sh infra/heartbeat.sh \
    infra/ecowitt-backup.service infra/ecowitt-backup.timer \
    infra/ecowitt-heartbeat.service infra/ecowitt-heartbeat.timer \
    "$INSTANCE:/tmp/" --zone="$ZONE" --tunnel-through-iap --quiet

echo "==> Installing"
"${SSH[@]}" --command="
set -euo pipefail
sudo install -d -o ecowitt -g ecowitt /opt/ecowitt
sudo install -m 755 -o ecowitt -g ecowitt /tmp/backup.sh /tmp/heartbeat.sh /opt/ecowitt/
# Substitute the real bucket for the CHANGEME placeholder.
sudo sed -e 's|CHANGEME-ecowitt-backups|$BACKUP_BUCKET|' /tmp/ecowitt-backup.service \
    | sudo tee /etc/systemd/system/ecowitt-backup.service >/dev/null
sudo install -m 644 /tmp/ecowitt-backup.timer /etc/systemd/system/
sudo install -m 644 /tmp/ecowitt-heartbeat.service /etc/systemd/system/
sudo install -m 644 /tmp/ecowitt-heartbeat.timer /etc/systemd/system/
grep -q '$BACKUP_BUCKET' /etc/systemd/system/ecowitt-backup.service \
    || { echo 'FATAL: bucket substitution failed'; exit 1; }
sudo systemctl daemon-reload
sudo systemctl enable --now ecowitt-backup.timer ecowitt-heartbeat.timer
echo '--- timers ---'
systemctl list-timers 'ecowitt-*' --no-pager
"
echo "==> Done."
