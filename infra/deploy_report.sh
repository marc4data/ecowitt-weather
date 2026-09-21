#!/usr/bin/env bash
# Deploy the daily email to the VM, prove it works, then turn it on.
#
#   LAKEHOUSE_EMAIL_TO='marc@x,stacy@x,tad@x' \
#   LAKEHOUSE_EMAIL_TEST_TO='marc@x' \
#   LAKEHOUSE_EMAIL_FROM='Lake House Monitor <station@example.com>' \
#   LAKEHOUSE_REPLY_TO='marc@x' \
#   LAKEHOUSE_STATION_URL='https://www.ecowitt.net/home/index?id=...' \
#   ./infra/deploy_report.sh
#
# ---------------------------------------------------------------------------
# THE ORDER MATTERS, and it is the whole design of this script.
#
#   1. Refuse to start unless the database and the secrets are already in place.
#      Discovering a missing role halfway through an install leaves a box in a
#      state nobody can describe.
#   2. Install the code and the units, with the timer still DISABLED.
#   3. Send one real --test email from the VM, to the test address.
#   4. Enable the timer ONLY IF that succeeded.
#
# Step 4 is the point. A scheduler enabled for something that has never run is
# a promise nobody has checked, and the first time it runs unattended is 07:00
# on the morning it is needed. `--skip-verify` exists for a redeploy where you
# already know it works; use it knowing what it skips.
# ---------------------------------------------------------------------------
set -euo pipefail

ZONE="${ZONE:-us-central1-a}"
INSTANCE="${INSTANCE:-ecowitt-db}"
PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
SSH=(gcloud compute ssh "$INSTANCE" --zone="$ZONE" --tunnel-through-iap --quiet)
# How much to prove before enabling the timer.
#
#   send   (default)  render on the VM AND send one --test email. Proves SMTP.
#   dry               render on the VM, send nothing. Proves the venv, both
#                     database roles, the checks and the charts -- everything
#                     except SMTP. Use when you do not want mail right now.
#   none              enable it blind. Nothing is proven.
VERIFY="${VERIFY:-send}"
case "${1:-}" in
    --dry-verify)  VERIFY=dry ;;
    --skip-verify) VERIFY=none ;;
esac

[[ -d src/reporting ]] || { echo "ERROR: run from the repo root" >&2; exit 2; }
: "${LAKEHOUSE_EMAIL_TO:?set it — refusing to install a unit with a placeholder recipient}"
: "${LAKEHOUSE_EMAIL_TEST_TO:?set it — the test list must never fall back to production}"
: "${LAKEHOUSE_EMAIL_FROM:?set it — the email needs a sender}"
# Optional: without it the emails simply carry no link to the live station.
LAKEHOUSE_STATION_URL="${LAKEHOUSE_STATION_URL:-}"
# Optional, but strongly wanted when the sender is automation-only: without it a
# reply to the morning email goes to a mailbox nobody opens.
LAKEHOUSE_REPLY_TO="${LAKEHOUSE_REPLY_TO:-}"
# Defaults to the sender, which is right whenever From carries no display name.
LAKEHOUSE_SMTP_USER="${LAKEHOUSE_SMTP_USER:-$LAKEHOUSE_EMAIL_FROM}"
# Optional: only an identity-linked Anthropic key needs it.
ANTHROPIC_WORKSPACE_ID="${ANTHROPIC_WORKSPACE_ID:-}"

say() { printf '\n==> %s\n' "$*"; }

# --- 1. preflight ---------------------------------------------------------
say "Checking prerequisites"

missing=0
for secret in ecowitt-readonly-password ecowitt-emailer-password lakehouse-smtp-password; do
    if gcloud secrets describe "$secret" --project="$PROJECT_ID" >/dev/null 2>&1; then
        printf '  secret %-28s ok\n' "$secret"
    else
        printf '  secret %-28s MISSING\n' "$secret"
        missing=1
    fi
done
if [[ "$missing" -eq 1 ]]; then
    cat >&2 <<'EOF'

REFUSED: a required secret is missing.

  ecowitt-readonly-password   ->  ./infra/create_readonly_user.sh
  ecowitt-emailer-password    ->  ./infra/create_emailer_user.sh
  lakehouse-smtp-password     ->  ./infra/create_report_secrets.sh
EOF
    exit 2
fi

db_state="$("${SSH[@]}" --command="
  printf 'table=%s role=%s' \
    \"\$(sudo -u ecowitt psql -tAqc \"select coalesce(to_regclass('public.email_log')::text,'absent')\" ecowitt)\" \
    \"\$(sudo -u postgres psql -tAqc \"select coalesce((select rolname from pg_roles where rolname='ecowitt_emailer'),'absent')\")\"
" 2>/dev/null | tr -d '\r')"
echo "  database  $db_state"
if [[ "$db_state" != *"table=email_log"* || "$db_state" != *"role=ecowitt_emailer"* ]]; then
    echo >&2
    echo "REFUSED: email_log or its writer role is missing. Run:" >&2
    echo "  ./infra/create_emailer_user.sh" >&2
    exit 2
fi

# systemd's Environment= does NOT strip a trailing "# comment", so a value that
# picked one up on its way here becomes part of the address list and the send
# fails at 07:00 with nothing to show for it. Caught once, in exactly that way.
for var in LAKEHOUSE_EMAIL_TO LAKEHOUSE_EMAIL_TEST_TO LAKEHOUSE_EMAIL_FROM LAKEHOUSE_REPLY_TO; do
    value="${!var}"
    [[ -z "$value" ]] && continue   # only REPLY_TO may be empty
    if [[ "$value" == *"#"* ]]; then
        echo >&2
        echo "REFUSED: $var contains a '#':" >&2
        echo "  ${value}" >&2
        echo >&2
        echo "systemd does not strip trailing comments. If this came from .env," >&2
        echo "the inline comment was not removed — parse it with python-dotenv." >&2
        exit 2
    fi
    # `Name <addr@host>` is legal; a bare address is legal; a bare address with
    # a stray space in it is not.
    bare="${value##*<}"; bare="${bare%>}"
    if [[ "$bare" != *"@"* || "$bare" == *" "* ]]; then
        echo "REFUSED: $var does not look like an email address: $value" >&2
        exit 2
    fi
done

if [[ "$LAKEHOUSE_EMAIL_TO" != *","* ]]; then
    echo
    echo "  NOTE: LAKEHOUSE_EMAIL_TO holds ONE address. Production email will reach"
    echo "        one person. That is allowed, and it looks identical to reaching"
    echo "        three — which is why §5.2 refuses to guess. Add the others when"
    echo "        you have them."
fi

# --- 2. install, timer still off -----------------------------------------
say "Staging application"
# What is actually going onto the box. R-009 round 1 found the install recorded
# no commit at all, so "what is the VM running" could only be answered by
# grepping its source for a string you already expected to find. A dirty tree
# is marked as such rather than quietly reported as its last commit.
DEPLOY_COMMIT="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
if ! git diff --quiet HEAD 2>/dev/null; then
    DEPLOY_COMMIT="$DEPLOY_COMMIT-dirty"
fi
echo "    commit: $DEPLOY_COMMIT"
# notebooks/*.py goes too: it owns the check thresholds this report reads, and
# copying them into src/ would be the two-implementations failure this project
# keeps designing against.
tar --no-xattrs -czf /tmp/ecowitt-report.tgz src pyproject.toml notebooks/ecowitt_daily.py notebooks/ecowitt_nb.py
gcloud compute scp /tmp/ecowitt-report.tgz infra/run_report.sh \
    infra/ecowitt-report.service infra/ecowitt-report.timer infra/heartbeat.sh \
    "$INSTANCE:/tmp/" --zone="$ZONE" --tunnel-through-iap --quiet

say "Installing on $INSTANCE"
"${SSH[@]}" --command="
set -euo pipefail
sudo install -d -o ecowitt -g ecowitt /opt/ecowitt/app
sudo tar xzf /tmp/ecowitt-report.tgz -C /opt/ecowitt/app
sudo install -m 755 -o ecowitt -g ecowitt /tmp/run_report.sh /opt/ecowitt/app/
# Replaces the ingestion heartbeat with the one that also watches email_log.
sudo install -m 755 -o ecowitt -g ecowitt /tmp/heartbeat.sh /opt/ecowitt/
sudo chown -R ecowitt:ecowitt /opt/ecowitt/app
# Recorded BEFORE the slow venv build, so a deploy that dies building pandas
# still leaves behind the truth about which source tree is on disk.
printf '%s\n' '${DEPLOY_COMMIT}' | sudo -u ecowitt tee /opt/ecowitt/app/VERSION >/dev/null

# The report needs pandas, matplotlib and sqlalchemy, which the ingestion job
# does not. This is the slow step on a 1 GB e2-micro -- several minutes, and it
# leans on the swap file. If it is ever OOM-killed, add swap rather than
# dropping the charts.
sudo -u ecowitt bash -c '
  cd /opt/ecowitt/app
  [[ -d venv ]] || python3 -m venv venv
  ./venv/bin/pip install -q --upgrade pip
  ./venv/bin/pip install -q -e \".[report]\"
'

sudo sed -e 's|CHANGEME-production-list|${LAKEHOUSE_EMAIL_TO}|' \
         -e 's|CHANGEME-marc-only|${LAKEHOUSE_EMAIL_TEST_TO}|' \
         -e 's|CHANGEME-sender|${LAKEHOUSE_EMAIL_FROM}|' \
         -e 's|CHANGEME-station-url|${LAKEHOUSE_STATION_URL}|' \
         -e 's|CHANGEME-reply-to|${LAKEHOUSE_REPLY_TO}|' \
         -e 's|CHANGEME-smtp-user|${LAKEHOUSE_SMTP_USER}|' \
         -e 's|CHANGEME-workspace-id|${ANTHROPIC_WORKSPACE_ID}|' \
    /tmp/ecowitt-report.service | sudo tee /etc/systemd/system/ecowitt-report.service >/dev/null
if grep -q 'CHANGEME-' /etc/systemd/system/ecowitt-report.service; then
    echo 'FATAL: a placeholder survived substitution'; exit 1
fi
sudo install -m 644 /tmp/ecowitt-report.timer /etc/systemd/system/
sudo systemctl daemon-reload
rm -f /tmp/ecowitt-report.tgz
echo 'installed as ${DEPLOY_COMMIT}; timer not enabled yet'
"

# --- 3. prove it works ----------------------------------------------------
# The addresses are passed explicitly: a manual run does not inherit the unit
# file's Environment= lines, only a systemd-started one does.
run_on_vm() {
    "${SSH[@]}" --command="
        sudo -u ecowitt \
          LAKEHOUSE_EMAIL_TO='${LAKEHOUSE_EMAIL_TO}' \
          LAKEHOUSE_EMAIL_TEST_TO='${LAKEHOUSE_EMAIL_TEST_TO}' \
          LAKEHOUSE_EMAIL_FROM='${LAKEHOUSE_EMAIL_FROM}' \
          LAKEHOUSE_STATION_URL='${LAKEHOUSE_STATION_URL}' \
          ECOWITT_NOTEBOOK_DIR=/opt/ecowitt/app/notebooks \
          /opt/ecowitt/app/run_report.sh $1"
}

case "$VERIFY" in
send)
    say "Sending one --test email from the VM to $LAKEHOUSE_EMAIL_TEST_TO"
    if run_on_vm --test; then
        say "That email arrived. Enabling the timer."
        "${SSH[@]}" --command="sudo systemctl enable --now ecowitt-report.timer"
    else
        cat >&2 <<'EOF'

REFUSED TO ENABLE THE TIMER: the test send failed.

Everything is installed and the timer is OFF, which is the right state: a
scheduler for something that has never worked would first run unattended at
07:00. Read the error above, fix it, and re-run this script.

  most likely      a wrong Gmail app password, or a sender that does not match
  see the reason   the run prints diagnose() output naming the fix
EOF
        exit 1
    fi
    ;;
dry)
    say "Building the report on the VM — rendering only, sending nothing"
    echo "    Proves: the venv, both database roles, the checks, the charts."
    echo "    Does NOT prove: SMTP. That stays untested until something sends."
    if run_on_vm ""; then
        say "It built. Enabling the timer."
        "${SSH[@]}" --command="sudo systemctl enable --now ecowitt-report.timer"
        cat <<'EOF'

  ⚠️  SMTP IS UNPROVEN. If the app password is wrong, the 07:00 run fails and
      the only symptom is an email that does not arrive — and the heartbeat's
      email-staleness check stays quiet until a production email has succeeded
      ONCE, so it will not catch a first send that never worked.

      If nothing arrives by ~07:15, read the journal:
        gcloud compute ssh ecowitt-db --zone=us-central1-a --tunnel-through-iap           --command='journalctl -u ecowitt-report.service -n 50 --no-pager'
EOF
    else
        echo >&2
        echo "REFUSED TO ENABLE THE TIMER: the report did not build on the VM." >&2
        exit 1
    fi
    ;;
none)
    say "Enabling the timer with NOTHING verified (--skip-verify)"
    "${SSH[@]}" --command="sudo systemctl enable --now ecowitt-report.timer"
    ;;
esac

say "Timers"
"${SSH[@]}" --command="systemctl list-timers 'ecowitt-*' --no-pager"

cat <<'EOF'

==> Live. Two things still worth doing, in this order:

  1. Prove an ACTION email can be delivered, not just an OK one. It is the
     path that only ever runs on a bad morning, so it is the least exercised:

       gcloud compute ssh ecowitt-db --zone=us-central1-a --tunnel-through-iap \
         --command="sudo -u ecowitt LAKEHOUSE_EMAIL_TO=x LAKEHOUSE_EMAIL_TEST_TO=you@x \
                    LAKEHOUSE_EMAIL_FROM=you@x /opt/ecowitt/app/run_report.sh --selftest --test"

  2. Verify the dead-man's switch by BREAKING it, per infra/README.md. Stop the
     timer, wait out MAX_EMAIL_AGE_MIN (26 h), and confirm the heartbeat turns
     unhealthy and Cloud Logging alerts. A switch nobody has tripped is a switch
     nobody knows the state of.

       sudo systemctl stop ecowitt-report.timer     # then wait, then start it

The first production email goes out at 07:00 America/Chicago and covers
yesterday. It reaches every address in LAKEHOUSE_EMAIL_TO.
EOF
