#!/usr/bin/env bash
# Wrapper: fetch database credentials into the environment, then run the report.
#
# Same arrangement as run_ingest.sh -- secrets reach the process through env
# vars and never touch disk (§10), and `set -x` here would defeat that entirely.
#
# TWO ROLES, NOT ONE (§8.4):
#   ecowitt_ro        reads the observation data; SELECT-only, read-only txns
#   ecowitt_emailer   writes email_log and nothing else
#
# Both connect over TCP to 127.0.0.1 rather than the unix socket. Peer auth maps
# the OS user to the database user, and this runs as `ecowitt` -- so a socket
# connection could only ever be the `ecowitt` role, which is read-write over
# everything. The loopback host line in the default pg_hba is what lets this
# process be something less privileged than the account it runs as.
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null || echo ecowitt-504320)}"
secret() { gcloud secrets versions access latest --secret="$1" --project="$PROJECT_ID"; }

RO_PW="$(secret ecowitt-readonly-password)"
EMAIL_PW="$(secret ecowitt-emailer-password)"
SMTP_PW="$(secret lakehouse-smtp-password)"
# Not a credential, but not publishable either: names, phone numbers, and who
# knows where the key is. It lives here for the same reason the passwords do.
# Optional — the email sends without it, saying plainly that nobody is named.
CONTACTS="$(secret lakehouse-contacts 2>/dev/null || true)"
# Optional. Without it the ACTION email still goes out, in the checks' own
# words -- triage is an enhancement, never a precondition (§6.3).
ANTHROPIC_KEY="$(secret anthropic-api-key 2>/dev/null || true)"

# ⚠️ PERCENT-ENCODE THE PASSWORDS. They go into a URL, and a password
# containing '@', '!', '/', '#' or ':' silently changes what that URL means --
# an '@' in the password makes libpq read everything before it as the host, and
# the failure is "failed to resolve host 'xyz!@127.0.0.1'", which names neither
# the password nor the real problem.
#
# The value reaches python on STDIN, never in argv, so it stays out of `ps`.
# `notebooks/ecowitt_nb.py` has always done this with quote_plus; this file did
# not, which is why the bug only ever appeared on the VM.
urlencode() { printf '%s' "$1" | python3 -c \
    'import sys, urllib.parse; print(urllib.parse.quote(sys.stdin.read(), safe=""))'; }

RO_PW_ENC="$(urlencode "$RO_PW")"
EMAIL_PW_ENC="$(urlencode "$EMAIL_PW")"

export ECOWITT_REPORT_DSN="postgresql+psycopg://ecowitt_ro:${RO_PW_ENC}@127.0.0.1:5432/ecowitt"
export ECOWITT_EMAIL_LOG_DSN="postgresql+psycopg://ecowitt_emailer:${EMAIL_PW_ENC}@127.0.0.1:5432/ecowitt"
export LAKEHOUSE_SMTP_PASSWORD="$SMTP_PW"
[[ -n "$CONTACTS" ]] && export LAKEHOUSE_CONTACTS="$CONTACTS"
[[ -n "$ANTHROPIC_KEY" ]] && export ANTHROPIC_API_KEY="$ANTHROPIC_KEY"

# The address lists are NOT secrets and are NOT defaulted here. An unset list is
# a refusal, in both directions (§5.2) -- so they are set in the unit file, where
# a reviewer can see who this machine emails without reading a secret store.
: "${LAKEHOUSE_EMAIL_TO:?not set — refusing rather than guessing a recipient list}"

cd /opt/ecowitt/app
exec ./venv/bin/python -m reporting.daily "$@"
