#!/usr/bin/env bash
# Create `email_log` and the one narrow role allowed to write it.
#
#   ./infra/create_emailer_user.sh
#
# ---------------------------------------------------------------------------
# Why a third role
#
# The report reads the observation data as `ecowitt_ro`, which is SELECT-only
# with `default_transaction_read_only` forced on -- and must stay that way. §8
# requires corrections to be recorded as changes rather than in-place
# overwrites, and the cheapest way to guarantee that is to make writes
# impossible for anything that only needs to read.
#
# So `email_log` gets its own login role that can touch nothing else: SELECT and
# INSERT on one table, and not even UPDATE or DELETE on that. The log of what
# was sent is evidence, and evidence is append-only.
#
# Idempotent: safe to re-run. The password is generated here, pushed straight to
# Secret Manager, and fetched by the VM's own service account -- it appears in
# no process list, local or remote, and never on disk.
# ---------------------------------------------------------------------------

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
ZONE="${ZONE:-us-central1-a}"
INSTANCE="${INSTANCE:-ecowitt-db}"
DB_NAME="${DB_NAME:-ecowitt}"
EMAIL_USER="${EMAIL_USER:-ecowitt_emailer}"
SECRET_NAME="${SECRET_NAME:-ecowitt-emailer-password}"

[[ -n "$PROJECT_ID" ]] || { echo "ERROR: no project set" >&2; exit 2; }
[[ -f schema/03_email_log.sql ]] || { echo "ERROR: run from the repo root" >&2; exit 2; }
say() { printf '\n==> %s\n' "$*"; }

# --- password -------------------------------------------------------------
# Hex, so it is safe to paste into any connection string without quoting.
if gcloud secrets describe "$SECRET_NAME" --project="$PROJECT_ID" >/dev/null 2>&1; then
    say "Secret $SECRET_NAME already exists — reusing that password"
else
    say "Generating password and storing it in Secret Manager"
    openssl rand -hex 24 | tr -d '\n' \
        | gcloud secrets create "$SECRET_NAME" --project="$PROJECT_ID" \
              --replication-policy=automatic --data-file=-
fi

gcloud secrets add-iam-policy-binding "$SECRET_NAME" --project="$PROJECT_ID" \
    --member="serviceAccount:ecowitt-vm@${PROJECT_ID}.iam.gserviceaccount.com" \
    --role=roles/secretmanager.secretAccessor --quiet >/dev/null

# --- remote setup ---------------------------------------------------------
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
cat > "$TMP/setup_emailer.sh" <<'REMOTE'
#!/usr/bin/env bash
set -euo pipefail
SECRET_NAME="$1"; EMAIL_USER="$2"; DB_NAME="$3"

# The table first. Owned by `ecowitt`, which owns every other table here.
if [[ "$(sudo -u ecowitt psql -tAqc "select coalesce(to_regclass('public.email_log')::text,'')" "$DB_NAME")" == "" ]]; then
    echo "creating email_log"
    sudo -u ecowitt psql -v ON_ERROR_STOP=1 -q -d "$DB_NAME" -f /tmp/03_email_log.sql
else
    echo "email_log already exists — leaving it alone"
fi

EMAIL_PW="$(gcloud secrets versions access latest --secret="$SECRET_NAME")"
export EMAIL_PW

# \getenv keeps the password out of psql's argv, so it never reaches `ps`.
sudo -u postgres EMAIL_PW="$EMAIL_PW" psql -v ON_ERROR_STOP=1 -q -d "$DB_NAME" \
     -v email_user="$EMAIL_USER" <<'SQL'
\getenv email_pw EMAIL_PW

SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'email_user', :'email_pw')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'email_user') \gexec

SELECT format('ALTER ROLE %I LOGIN PASSWORD %L', :'email_user', :'email_pw') \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), :'email_user') \gexec
SELECT format('GRANT USAGE ON SCHEMA public TO %I', :'email_user') \gexec
SELECT format('REVOKE CREATE ON SCHEMA public FROM %I', :'email_user') \gexec
SQL

# The grants on the table belong to its OWNER, not to postgres.
sudo -u ecowitt psql -v ON_ERROR_STOP=1 -q -d "$DB_NAME" -v email_user="$EMAIL_USER" <<'SQL'
-- SELECT as well as INSERT: the duplicate check reads this table before the
-- send, and a writer that cannot read its own table would have to send first
-- and ask afterwards.
SELECT format('GRANT SELECT, INSERT ON email_log TO %I', :'email_user') \gexec
SELECT format('GRANT USAGE ON SEQUENCE email_log_email_id_seq TO %I', :'email_user') \gexec
-- Deliberately NOT granted: UPDATE and DELETE, on this or anything else.
SQL

echo "role $EMAIL_USER configured"
REMOTE

say "Staging to $INSTANCE"
gcloud compute scp schema/03_email_log.sql "$TMP/setup_emailer.sh" \
    "$INSTANCE:/tmp/" --zone="$ZONE" --tunnel-through-iap --quiet

say "Creating email_log and role $EMAIL_USER"
gcloud compute ssh "$INSTANCE" --zone="$ZONE" --tunnel-through-iap --quiet \
    --command="chmod +x /tmp/setup_emailer.sh && /tmp/setup_emailer.sh '$SECRET_NAME' '$EMAIL_USER' '$DB_NAME' && rm -f /tmp/setup_emailer.sh /tmp/03_email_log.sql"

# --- verify it is genuinely narrow ----------------------------------------
# Not politeness: this role's password sits in an environment variable on a box
# that also runs the ingestion job, and "can only append to one table" is the
# property that makes that uninteresting to an attacker.
say "Verifying the role can write email_log and nothing else"
gcloud compute ssh "$INSTANCE" --zone="$ZONE" --tunnel-through-iap --quiet --command="
sudo -u postgres psql -qtA -d '$DB_NAME' <<'SQL'
SELECT '  can log in       : ' || rolcanlogin || '  superuser: ' || rolsuper
  FROM pg_roles WHERE rolname = '$EMAIL_USER';
SELECT '  email_log grants : ' || string_agg(privilege_type, ', ' ORDER BY privilege_type)
  FROM information_schema.role_table_grants
 WHERE grantee = '$EMAIL_USER' AND table_name = 'email_log';
SELECT '  other tables     : ' || coalesce(string_agg(DISTINCT table_name, ', '), 'none')
  FROM information_schema.role_table_grants
 WHERE grantee = '$EMAIL_USER' AND table_name <> 'email_log';
SQL
"

cat <<EOF

==> Done. Expect: can log in = t, superuser = f, grants = INSERT, SELECT,
    other tables = none.

Next: ./infra/create_report_secrets.sh
EOF
