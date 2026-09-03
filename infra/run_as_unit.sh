#!/usr/bin/env bash
# Run the report on the VM with EXACTLY the environment systemd would give it.
#
#   ./infra/run_as_unit.sh                 # dry run: renders, sends nothing
#   ./infra/run_as_unit.sh --test          # sends to the TEST address only
#   ./infra/run_as_unit.sh --selftest --test
#
# Why this exists: a manual `run_report.sh` does NOT inherit the unit file's
# Environment= lines — only a systemd-started run does. Retyping them by hand
# tests a configuration nobody deployed, and the one time that mattered it hid
# an address with a comment glued to it. This reads the environment back out of
# systemd and uses that, so a manual run and the 07:00 run differ in exactly one
# way: the flags.
#
# `--send` is refused here. Production sending is the timer's job; doing it by
# hand is how a day gets emailed twice or emailed early.
set -euo pipefail

ZONE="${ZONE:-us-central1-a}"
INSTANCE="${INSTANCE:-ecowitt-db}"

for arg in "$@"; do
    if [[ "$arg" == "--send" ]]; then
        echo "REFUSED: --send belongs to the timer. Use --test, or wait for 07:00." >&2
        exit 2
    fi
done

read -r -d '' REMOTE <<'PYEOF' || true
import os, shlex, subprocess, sys
raw = subprocess.run(
    ["systemctl", "show", "ecowitt-report.service", "-p", "Environment", "--value"],
    capture_output=True, text=True, check=True).stdout.strip()
# shlex, because systemd quotes any value containing spaces -- a display name in
# From is exactly such a value, and splitting on whitespace would shred it.
env = dict(t.split("=", 1) for t in shlex.split(raw) if "=" in t)
if not env.get("LAKEHOUSE_EMAIL_TO"):
    sys.exit("the unit has no LAKEHOUSE_EMAIL_TO — is the report deployed?")
os.execve("/opt/ecowitt/app/run_report.sh",
          ["run_report.sh", *sys.argv[1:]], {**os.environ, **env})
PYEOF

gcloud compute ssh "$INSTANCE" --zone="$ZONE" --tunnel-through-iap --quiet --command="
  printf '%s' $(printf '%q' "$REMOTE") > /tmp/run_as_unit.py
  sudo -u ecowitt python3 /tmp/run_as_unit.py $*
  rc=\$?; rm -f /tmp/run_as_unit.py; exit \$rc
"
