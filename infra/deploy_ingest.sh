#!/usr/bin/env bash
# Deploy the ingestion job to the VM and install its timers.
#   ./infra/deploy_ingest.sh
set -euo pipefail

ZONE="${ZONE:-us-central1-a}"
INSTANCE="${INSTANCE:-ecowitt-db}"
SSH=(gcloud compute ssh "$INSTANCE" --zone="$ZONE" --tunnel-through-iap --quiet)

[[ -d src/ingest ]] || { echo "ERROR: run from the repo root" >&2; exit 2; }

echo "==> Staging application"
tar czf /tmp/ecowitt-app.tgz src pyproject.toml
gcloud compute scp /tmp/ecowitt-app.tgz infra/run_ingest.sh \
    infra/ecowitt-ingest.service infra/ecowitt-ingest.timer \
    infra/ecowitt-reconcile.service infra/ecowitt-reconcile.timer \
    "$INSTANCE:/tmp/" --zone="$ZONE" --tunnel-through-iap --quiet

echo "==> Installing"
"${SSH[@]}" --command='
set -euo pipefail
sudo install -d -o ecowitt -g ecowitt /opt/ecowitt/app /opt/ecowitt/raw
sudo tar xzf /tmp/ecowitt-app.tgz -C /opt/ecowitt/app
sudo install -m 755 -o ecowitt -g ecowitt /tmp/run_ingest.sh /opt/ecowitt/app/
sudo chown -R ecowitt:ecowitt /opt/ecowitt/app

# Build the venv as the ecowitt user so it owns everything it will import.
sudo -u ecowitt bash -c "
  cd /opt/ecowitt/app
  [[ -d venv ]] || python3 -m venv venv
  ./venv/bin/pip install -q --upgrade pip
  ./venv/bin/pip install -q -e .
"
for u in ecowitt-ingest ecowitt-reconcile; do
  sudo install -m 644 /tmp/$u.service /tmp/$u.timer /etc/systemd/system/
done
sudo systemctl daemon-reload
sudo systemctl enable --now ecowitt-ingest.timer ecowitt-reconcile.timer
echo "--- timers ---"
systemctl list-timers "ecowitt-*" --no-pager
'
echo "==> Done."
