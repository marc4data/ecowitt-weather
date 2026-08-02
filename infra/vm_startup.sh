#!/usr/bin/env bash
# VM startup script — installs and configures PostgreSQL 16 on the e2-micro.
#
# Runs as root on every boot. Written to be idempotent: re-running must not
# damage an existing database, so every step checks before acting.
#
# Deliberately contains NO secrets. The ingestion job connects over a unix
# socket using peer authentication, so there is no database password to leak
# (§10). Ecowitt API credentials live in Secret Manager and are fetched at
# runtime by the VM's service account.

set -euo pipefail
exec > >(tee -a /var/log/ecowitt-startup.log) 2>&1
echo "=== ecowitt startup $(date -u +%FT%TZ) ==="

DB_NAME="ecowitt"
DB_USER="ecowitt"
# Debian 12 ships PostgreSQL 15 in its own repos, so 16 comes from PGDG (the
# upstream Postgres apt repo). PG_VERSION is the version we ASK for; the
# version actually installed is detected afterwards rather than assumed --
# hardcoding it is what broke the first run of this script.
PG_WANTED="16"

# ---------------------------------------------------------------------------
# Swap. e2-micro has 1 GB of RAM and shares a core. Postgres plus a Python
# process will not comfortably fit at peak, and the OOM killer taking out the
# database mid-write is exactly the silent failure §10 is about.
# ---------------------------------------------------------------------------
if [[ ! -f /swapfile ]]; then
    echo "--- creating 2G swapfile"
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    # Prefer reclaiming cache over swapping Postgres out.
    sysctl -w vm.swappiness=10
    echo 'vm.swappiness=10' > /etc/sysctl.d/99-ecowitt.conf
fi

# ---------------------------------------------------------------------------
# PostgreSQL
# ---------------------------------------------------------------------------
if ! command -v psql >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq curl ca-certificates gnupg python3-venv python3-pip

    # PGDG repo, per the official Postgres instructions.
    CODENAME="$(. /etc/os-release && echo "$VERSION_CODENAME")"
    if [[ ! -f /etc/apt/sources.list.d/pgdg.list ]]; then
        echo "--- adding PGDG repo for $CODENAME"
        install -d /usr/share/postgresql-common/pgdg
        curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
            -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc
        echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc]" \
             "https://apt.postgresql.org/pub/repos/apt ${CODENAME}-pgdg main" \
            > /etc/apt/sources.list.d/pgdg.list
        apt-get update -qq
    fi

    # Fall back to whatever the distro ships rather than failing outright: a
    # working Postgres 15 beats a VM with no database because an upstream repo
    # was unreachable.
    if apt-get install -y -qq "postgresql-$PG_WANTED"; then
        echo "--- installed postgresql-$PG_WANTED from PGDG"
    else
        echo "--- PGDG postgresql-$PG_WANTED unavailable; falling back to distro default"
        apt-get install -y -qq postgresql
    fi
fi

# Detect what is actually installed instead of assuming.
PG_VERSION="$(ls -1 /etc/postgresql 2>/dev/null | sort -V | tail -1)"
[[ -n "$PG_VERSION" ]] || { echo "FATAL: no /etc/postgresql/<version> found"; exit 1; }
echo "--- postgres version in use: $PG_VERSION"

PGCONF="/etc/postgresql/$PG_VERSION/main/conf.d/ecowitt.conf"
if [[ ! -f "$PGCONF" ]]; then
    echo "--- writing $PGCONF"
    mkdir -p "$(dirname "$PGCONF")"
    cat > "$PGCONF" <<'CONF'
# Tuned for 1 GB RAM on a shared core. Conservative on purpose: this box runs
# a batch job that writes ~12k rows every few minutes, not a serving workload.
shared_buffers = 128MB
effective_cache_size = 512MB
work_mem = 4MB
maintenance_work_mem = 64MB
max_connections = 20

# Never listen on anything but localhost. There is no firewall rule opening
# 5432, and there should never be one -- the job runs on this box.
listen_addresses = 'localhost'

# §8: raw landing is append-only and history must be reconstructable. Keep
# enough WAL to make a PITR-style recovery from a base backup possible.
wal_level = replica
max_wal_size = 512MB
min_wal_size = 80MB

# A slow query or a stalled checkpoint is an early warning. Log both.
log_min_duration_statement = 5000
log_checkpoints = on
log_connections = off
log_line_prefix = '%m [%p] %q%u@%d '
CONF
    systemctl restart postgresql
fi

systemctl enable postgresql
systemctl start postgresql

# ---------------------------------------------------------------------------
# Role and database.
#
# Peer authentication over the unix socket: the OS user `ecowitt` connects as
# the DB user `ecowitt` with no password. Nothing to store, nothing to rotate,
# nothing to leak. This is the main security advantage of colocating the job.
# ---------------------------------------------------------------------------
if ! id -u "$DB_USER" >/dev/null 2>&1; then
    echo "--- creating OS user $DB_USER"
    useradd --create-home --shell /bin/bash "$DB_USER"
fi

if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1; then
    echo "--- creating role $DB_USER"
    sudo -u postgres createuser "$DB_USER"
fi

if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1; then
    echo "--- creating database $DB_NAME"
    sudo -u postgres createdb --owner="$DB_USER" "$DB_NAME"
fi

echo "=== startup complete ==="
echo "Schema is NOT applied automatically — it is a reviewed, one-time step."
echo "  gcloud compute ssh ecowitt-db --tunnel-through-iap"
echo "  sudo -u ecowitt psql ecowitt -f /opt/ecowitt/schema/00_common.sql"
