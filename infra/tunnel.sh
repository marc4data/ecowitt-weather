#!/usr/bin/env bash
# Open an SSH tunnel to the database for pgAdmin / DBeaver, and don't return
# until it is actually accepting connections.
#
#   ./infra/tunnel.sh          # foreground; Ctrl-C to close
#   ./infra/tunnel.sh --check  # report status and exit
#
# ---------------------------------------------------------------------------
# Why this exists
#
# The plain gcloud command is easy to run on the wrong machine. Inside the VM
# or Cloud Shell it fails with an opaque IAM error ("Required
# 'compute.instances.get' permission") that says nothing about the real
# problem, which is that you are not on your workstation. The shell prompt
# looks identical in all three places.
#
# So this refuses to run anywhere but a workstation, says why, and then waits
# for the port to genuinely accept a connection instead of returning the
# instant ssh forks -- because "the command didn't error" and "pgAdmin can
# connect" are not the same thing.
# ---------------------------------------------------------------------------

set -euo pipefail

ZONE="${ZONE:-us-central1-a}"
INSTANCE="${INSTANCE:-ecowitt-db}"
LOCAL_PORT="${LOCAL_PORT:-5433}"
REMOTE_PORT="${REMOTE_PORT:-5432}"
DB_NAME="${DB_NAME:-ecowitt}"
RO_USER="${RO_USER:-ecowitt_ro}"
SECRET_NAME="${SECRET_NAME:-ecowitt-readonly-password}"

listening() {
    if command -v lsof >/dev/null 2>&1; then
        lsof -nP -iTCP:"$LOCAL_PORT" -sTCP:LISTEN >/dev/null 2>&1
    else
        ss -lnt 2>/dev/null | grep -q ":$LOCAL_PORT "
    fi
}

# --- refuse to run in the wrong place -------------------------------------
if [[ "$(hostname -s 2>/dev/null || hostname)" == "$INSTANCE" ]]; then
    cat >&2 <<EOF
ERROR: you are running this ON $INSTANCE, not on your workstation.

A tunnel forwards a port from your machine to this one, so running it here
does nothing. It would also fail: gcloud on the VM authenticates as the VM's
service account, which deliberately lacks compute.instances.get.

  * To query from here, no tunnel is needed:   sudo -u ecowitt psql $DB_NAME
  * To use pgAdmin, type 'exit' first, then run this on your workstation.
EOF
    exit 2
fi

if [[ -n "${CLOUD_SHELL:-}" || -n "${DEVSHELL_PROJECT_ID:-}" ]]; then
    echo "ERROR: this is Cloud Shell. pgAdmin runs on your workstation; the tunnel must too." >&2
    exit 2
fi

ACCOUNT="$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null || true)"
if [[ "$ACCOUNT" == *".gserviceaccount.com" ]]; then
    echo "ERROR: gcloud is authenticated as a service account ($ACCOUNT)." >&2
    echo "       Run 'gcloud auth login' as yourself first." >&2
    exit 2
fi

# --- status ---------------------------------------------------------------
if [[ "${1:-}" == "--check" ]]; then
    if listening; then
        echo "tunnel is UP on localhost:$LOCAL_PORT"
        exit 0
    fi
    echo "tunnel is DOWN (nothing listening on $LOCAL_PORT)"
    exit 1
fi

if listening; then
    echo "Port $LOCAL_PORT is already in use — a tunnel is probably already open."
    echo "Close it first, or set LOCAL_PORT to something else."
    exit 0
fi

# --- open it --------------------------------------------------------------
echo "Opening tunnel localhost:$LOCAL_PORT -> $INSTANCE:$REMOTE_PORT ..."
gcloud compute ssh "$INSTANCE" --zone="$ZONE" --tunnel-through-iap --quiet \
    -- -N -L "$LOCAL_PORT:localhost:$REMOTE_PORT" &
SSH_PID=$!
trap 'kill $SSH_PID 2>/dev/null || true' EXIT INT TERM

# Wait for the port to actually accept a connection. `ssh` forking is not the
# same thing as the forward being usable, and returning early is how you end up
# staring at "connection refused" in a GUI.
for _ in $(seq 1 60); do
    listening && break
    kill -0 "$SSH_PID" 2>/dev/null || { echo "ERROR: ssh exited before the tunnel came up" >&2; exit 1; }
    sleep 1
done
listening || { echo "ERROR: tunnel did not come up within 60s" >&2; exit 1; }

cat <<EOF

Tunnel is UP and accepting connections.

  Host      127.0.0.1
  Port      $LOCAL_PORT
  Database  $DB_NAME
  Username  $RO_USER
  Password  gcloud secrets versions access latest --secret=$SECRET_NAME

Leave this window open while you use pgAdmin. Ctrl-C closes the tunnel.
EOF

wait "$SSH_PID"
