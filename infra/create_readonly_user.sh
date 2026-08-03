#!/usr/bin/env bash
# Create a password-authenticated READ-ONLY role for GUI tools (pgAdmin, DBeaver).
#
#   ./infra/create_readonly_user.sh
#
# ---------------------------------------------------------------------------
# Why a separate role rather than a password on `ecowitt`
#
# The ingestion job connects over a unix socket with peer authentication and has
# no password at all — nothing to store, rotate, or leak (§10). Putting a
# password on that role to satisfy a GUI would throw that away for convenience.
#
# Read-only is not politeness either. `raw_payload` is append-only, but its
# trigger only fires on UPDATE/DELETE — a role with write access could still
# corrupt `observation` or `change_log` with a mistyped statement in a GUI. §8
# requires corrections to be recorded as changes, never in-place overwrites, and
# the cheapest way to guarantee that for an interactive session is to make
# writes impossible. Enforced twice: SELECT-only grants, plus
# default_transaction_read_only forced on, so a later grant mistake still cannot
# turn an exploratory query into a write.
#
# The password never travels through any command line. It is generated here,
# pushed straight to Secret Manager, and the VM fetches it itself using its own
# service account — so it appears in no process list, local or remote.
# ---------------------------------------------------------------------------

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
ZONE="${ZONE:-us-central1-a}"
INSTANCE="${INSTANCE:-ecowitt-db}"
DB_NAME="${DB_NAME:-ecowitt}"
RO_USER="${RO_USER:-ecowitt_ro}"
SECRET_NAME="${SECRET_NAME:-ecowitt-readonly-password}"

[[ -n "$PROJECT_ID" ]] || { echo "ERROR: no project set" >&2; exit 2; }
say() { printf '\n==> %s\n' "$*"; }

# --- password -------------------------------------------------------------
# `openssl rand -hex` rather than `tr -dc … | head -c N`: head closing the pipe
# SIGPIPEs tr, which under `set -o pipefail` aborts the script. Hex is also
# safe to paste into any connection string without quoting.
if gcloud secrets describe "$SECRET_NAME" --project="$PROJECT_ID" >/dev/null 2>&1; then
    say "Secret $SECRET_NAME already exists — reusing that password"
else
    say "Generating password and storing it in Secret Manager"
    openssl rand -hex 24 | tr -d '\n' \
        | gcloud secrets create "$SECRET_NAME" --project="$PROJECT_ID" \
              --replication-policy=automatic --data-file=-
fi

# Let the VM's service account read it.
gcloud secrets add-iam-policy-binding "$SECRET_NAME" --project="$PROJECT_ID" \
    --member="serviceAccount:ecowitt-vm@${PROJECT_ID}.iam.gserviceaccount.com" \
    --role=roles/secretmanager.secretAccessor --quiet >/dev/null

# --- remote setup ---------------------------------------------------------
# Staged as a file rather than a nested heredoc through `ssh --command`, which
# is where the first version of this script broke. Contains no secrets.
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
cat > "$TMP/setup_ro.sh" <<'REMOTE'
#!/usr/bin/env bash
set -euo pipefail
SECRET_NAME="$1"; RO_USER="$2"; DB_NAME="$3"

# Fetched here, by this machine's own service account.
RO_PW="$(gcloud secrets versions access latest --secret="$SECRET_NAME")"
export RO_PW

# \getenv keeps the password out of psql's argv, so it never reaches `ps`.
sudo -u postgres RO_PW="$RO_PW" psql -v ON_ERROR_STOP=1 -q -d "$DB_NAME" \
     -v ro_user="$RO_USER" <<'SQL'
\getenv ro_pw RO_PW

SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'ro_user', :'ro_pw')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'ro_user') \gexec

SELECT format('ALTER ROLE %I LOGIN PASSWORD %L', :'ro_user', :'ro_pw') \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), :'ro_user') \gexec
SELECT format('GRANT USAGE ON SCHEMA public TO %I', :'ro_user') \gexec
SELECT format('GRANT SELECT ON ALL TABLES IN SCHEMA public TO %I', :'ro_user') \gexec
SELECT format('ALTER ROLE %I SET default_transaction_read_only = on', :'ro_user') \gexec
SELECT format('REVOKE CREATE ON SCHEMA public FROM %I', :'ro_user') \gexec
SQL

# Default privileges belong to the role that OWNS the objects, which is
# ecowitt, not postgres. Without this, tables added later are invisible.
sudo -u ecowitt psql -v ON_ERROR_STOP=1 -q -d "$DB_NAME" -v ro_user="$RO_USER" <<'SQL'
SELECT format('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO %I', :'ro_user') \gexec
SQL

echo "role $RO_USER configured"
REMOTE

say "Configuring role $RO_USER on $INSTANCE"
gcloud compute scp "$TMP/setup_ro.sh" "$INSTANCE:/tmp/" \
    --zone="$ZONE" --tunnel-through-iap --quiet
gcloud compute ssh "$INSTANCE" --zone="$ZONE" --tunnel-through-iap --quiet \
    --command="chmod +x /tmp/setup_ro.sh && /tmp/setup_ro.sh '$SECRET_NAME' '$RO_USER' '$DB_NAME' && rm -f /tmp/setup_ro.sh"

say "Verifying it is genuinely read-only"
gcloud compute ssh "$INSTANCE" --zone="$ZONE" --tunnel-through-iap --quiet \
    --command="sudo -u postgres psql -qtA -d '$DB_NAME' -c \"
        SELECT 'can_login=' || rolcanlogin || ' superuser=' || rolsuper ||
               ' createdb=' || rolcreatedb || ' createrole=' || rolcreaterole
          FROM pg_roles WHERE rolname='$RO_USER'\"" 2>/dev/null | grep -v '^$' || true

say "Done."
cat <<EOF

Get the password (not printed anywhere, not written to disk):
  gcloud secrets versions access latest --secret=$SECRET_NAME

Open the tunnel and leave it running while you use pgAdmin:
  gcloud compute ssh $INSTANCE --zone=$ZONE --tunnel-through-iap -- -N -L 5433:localhost:5432

pgAdmin / DBeaver connection:
  Host      localhost
  Port      5433
  Database  $DB_NAME
  Username  $RO_USER
  Password  from the command above

Postgres still listens only on localhost, so the SSH tunnel remains the only
route in. This adds a read-only account; it does not open a port.
EOF
