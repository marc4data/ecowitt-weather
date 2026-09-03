#!/usr/bin/env bash
# Put the daily email's secrets into Secret Manager, and let the VM read them.
#
#   ./infra/create_report_secrets.sh              # prompts for each value
#   ./infra/create_report_secrets.sh --from-env   # takes them from .env
#
# `--from-env` reads the values already in the gitignored `.env`, so the same
# secrets that make the report work on this machine are the ones the VM gets.
# Nothing is echoed either way.
#
# Prompts for each value and reads it with `read -s`, so nothing lands in the
# shell history, in `ps`, or on the terminal. Values reach Secret Manager over
# stdin, never as an argument.
#
# Three secrets, one required:
#
#   lakehouse-smtp-password   REQUIRED. Gmail app password, 16 characters.
#   anthropic-api-key         optional. Without it the ACTION emails still send,
#                             written by the checks rather than by Claude.
#   lakehouse-contacts        optional. Who to call, as JSON. Kept here rather
#                             than in the repo because it is other people's
#                             names and phone numbers.
#
# Re-runnable: an existing secret gets a NEW VERSION rather than an error, so
# this is also how a password is rotated.
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
SERVICE_ACCOUNT="ecowitt-vm@${PROJECT_ID}.iam.gserviceaccount.com"

[[ -n "$PROJECT_ID" ]] || { echo "ERROR: no project set" >&2; exit 2; }
say() { printf '\n==> %s\n' "$*"; }

FROM_ENV=0
[[ "${1:-}" == "--from-env" ]] && FROM_ENV=1
if [[ "$FROM_ENV" -eq 1 ]]; then
    [[ -f .env ]] || { echo "ERROR: no .env in $(pwd)" >&2; exit 2; }
    # Parsed by python-dotenv, NOT by grep/cut. `.env` allows inline comments
    # and quoting, and a hand-rolled parser gets them subtly wrong: a line like
    #     LAKEHOUSE_EMAIL_TO=a@x,b@x  # the household
    # yields a value with "  # the household" glued to the last address. The
    # application reads this file with dotenv, so anything deployed elsewhere
    # must read it the same way or the two quietly disagree.
    #
    # Sourcing is deliberately avoided too: it would execute whatever is in
    # there, and this script runs with your credentials.
    read_env() {
        python3 - "$1" <<'PYEOF'
import sys
try:
    from dotenv import dotenv_values
except ImportError:
    sys.exit("ERROR: python-dotenv is needed to read .env; pip install python-dotenv")
print(dotenv_values(".env").get(sys.argv[1]) or "", end="")
PYEOF
    }
    SMTP_PW="$(read_env LAKEHOUSE_SMTP_PASSWORD)"
    ANTHROPIC_KEY="$(read_env ANTHROPIC_API_KEY)"
    CONTACTS="$(read_env LAKEHOUSE_CONTACTS)"
    say "Reading values from .env (nothing is printed)"
    printf '  %-26s %s\n' LAKEHOUSE_SMTP_PASSWORD "$([[ -n "$SMTP_PW" ]] && echo "found, ${#SMTP_PW} chars" || echo MISSING)"
    printf '  %-26s %s\n' ANTHROPIC_API_KEY "$([[ -n "$ANTHROPIC_KEY" ]] && echo "found, ${#ANTHROPIC_KEY} chars" || echo "absent — skipping")"
    printf '  %-26s %s\n' LAKEHOUSE_CONTACTS "$([[ -n "$CONTACTS" ]] && echo "found" || echo "absent — skipping")"
fi

store() {
    local name="$1" value="$2"
    if gcloud secrets describe "$name" --project="$PROJECT_ID" >/dev/null 2>&1; then
        printf '%s' "$value" | gcloud secrets versions add "$name" \
            --project="$PROJECT_ID" --data-file=- >/dev/null
        echo "  $name — new version added"
    else
        printf '%s' "$value" | gcloud secrets create "$name" \
            --project="$PROJECT_ID" --replication-policy=automatic --data-file=- >/dev/null
        echo "  $name — created"
    fi
    # The VM fetches these itself, using its own service account. No key
    # material is ever copied to the box.
    gcloud secrets add-iam-policy-binding "$name" --project="$PROJECT_ID" \
        --member="serviceAccount:${SERVICE_ACCOUNT}" \
        --role=roles/secretmanager.secretAccessor --quiet >/dev/null
}

if [[ "$FROM_ENV" -eq 0 ]]; then
    say "Gmail app password (REQUIRED)"
    echo "  16 characters, from https://myaccount.google.com/apppasswords"
    echo "  An ordinary account password is always rejected by Gmail."
    read -rsp "  password (input hidden): " SMTP_PW; echo
fi
say "Storing the Gmail app password"
[[ -n "$SMTP_PW" ]] || { echo "ERROR: required" >&2; exit 2; }
# Spaces are how Google displays it; they are not part of the password.
SMTP_PW="${SMTP_PW// /}"
if [[ ${#SMTP_PW} -ne 16 ]]; then
    echo "  WARNING: that is ${#SMTP_PW} characters, not 16 — app passwords are 16."
    read -rp "  store it anyway? [y/N] " ok
    [[ "$ok" == "y" || "$ok" == "Y" ]] || exit 2
fi
store lakehouse-smtp-password "$SMTP_PW"

if [[ "$FROM_ENV" -eq 0 ]]; then
    say "Anthropic API key (optional — press Enter to skip)"
    echo "  Adds a plain-English opening to ACTION emails. Without it they still send."
    read -rsp "  key (input hidden): " ANTHROPIC_KEY; echo
else
    say "Anthropic API key"
fi
if [[ -n "$ANTHROPIC_KEY" ]]; then
    store anthropic-api-key "$ANTHROPIC_KEY"
    echo "  NOTE: if this key is identity-linked, ANTHROPIC_WORKSPACE_ID must also be"
    echo "        set in infra/ecowitt-report.service. Check with:"
    echo "        python -m reporting.triage --check"
else
    echo "  skipped"
fi

say "Contacts"
if [[ "$FROM_ENV" -eq 0 && -z "${CONTACTS:-}" ]]; then
    echo '  JSON, e.g. [{"who":"Some HVAC Co","what":"services the A/C"}]'
    read -rp "  contacts JSON (or Enter to skip): " CONTACTS
fi
if [[ -n "${CONTACTS:-}" ]]; then
    if ! printf '%s' "$CONTACTS" | python3 -c 'import json,sys; json.load(sys.stdin)' 2>/dev/null; then
        echo "ERROR: that is not valid JSON — not storing it" >&2
        exit 2
    fi
    store lakehouse-contacts "$CONTACTS"
else
    echo "  skipped — ACTION emails will say no contact is configured"
fi

say "What the VM can now read"
for name in ecowitt-readonly-password ecowitt-emailer-password \
            lakehouse-smtp-password anthropic-api-key lakehouse-contacts; do
    if gcloud secrets describe "$name" --project="$PROJECT_ID" >/dev/null 2>&1; then
        printf '  %-28s present\n' "$name"
    else
        printf '  %-28s MISSING\n' "$name"
    fi
done

cat <<'EOF'

==> Done. `ecowitt-readonly-password` and `ecowitt-emailer-password` must both
    say present — the first is created by create_readonly_user.sh, the second by
    create_emailer_user.sh.

Next: ./infra/deploy_report.sh
EOF
