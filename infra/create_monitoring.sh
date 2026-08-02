#!/usr/bin/env bash
# Alerting for the two ways this pipeline can fail silently.
#
#   ./infra/create_monitoring.sh --dry-run
#   ALERT_EMAIL=you@example.com ./infra/create_monitoring.sh
#
# ---------------------------------------------------------------------------
# Why two policies and not one
#
# CLAUDE.md §10: "A silently dead scheduled job is the primary risk to this
# project." There are two distinct silences, and an alert on errors catches
# only the first:
#
#   1. The box is alive and knows something is wrong -> heartbeat.sh emits an
#      ERROR entry. Policy "unhealthy" fires on it.
#
#   2. The box is dead, or the timer stopped, or Postgres is gone -> NOTHING is
#      emitted. No error, no alert, and a dashboard full of green. Policy
#      "not reporting" fires on the ABSENCE of heartbeats. This is the one that
#      matters, and it is the one an error-only alert would miss.
#
# This is the same argument §7 makes for run_log: absence of a row is the
# signal. Here, absence of a metric is.
# ---------------------------------------------------------------------------

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
ALERT_EMAIL="${ALERT_EMAIL:-$(gcloud config get-value account 2>/dev/null)}"
LOG_NAME="${LOG_NAME:-ecowitt-heartbeat}"
ABSENCE_DURATION="${ABSENCE_DURATION:-3600s}"   # heartbeat runs every 15 min

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1
say() { printf '\n==> %s\n' "$*"; }
run() { if [[ $DRY_RUN -eq 1 ]]; then printf '  [dry-run] %s\n' "$*"; else "$@"; fi; }

[[ -n "$PROJECT_ID" ]] || { echo "ERROR: no project set" >&2; exit 2; }
[[ -n "$ALERT_EMAIL" ]] || { echo "ERROR: set ALERT_EMAIL" >&2; exit 2; }

say "Project $PROJECT_ID · alerts to $ALERT_EMAIL"

run gcloud services enable monitoring.googleapis.com --project="$PROJECT_ID"

# --- log-based metrics ----------------------------------------------------
# Entries are written by `gcloud logging write`, so resource.type is "global".
say "Creating log-based metrics"
if gcloud logging metrics describe ecowitt_heartbeat --project="$PROJECT_ID" >/dev/null 2>&1; then
    echo "  ecowitt_heartbeat exists"
else
    run gcloud logging metrics create ecowitt_heartbeat \
        --project="$PROJECT_ID" \
        --description="Every heartbeat emission, healthy or not. Absence means the pipeline is gone." \
        --log-filter="logName=\"projects/$PROJECT_ID/logs/$LOG_NAME\""
fi

if gcloud logging metrics describe ecowitt_heartbeat_unhealthy --project="$PROJECT_ID" >/dev/null 2>&1; then
    echo "  ecowitt_heartbeat_unhealthy exists"
else
    run gcloud logging metrics create ecowitt_heartbeat_unhealthy \
        --project="$PROJECT_ID" \
        --description="Heartbeats reporting a stale run, stale backup, or wedged run." \
        --log-filter="logName=\"projects/$PROJECT_ID/logs/$LOG_NAME\" AND severity=ERROR"
fi

# --- notification channel -------------------------------------------------
# Uses the Monitoring REST API rather than `gcloud alpha/beta monitoring`.
# Those command groups are not installed, and `gcloud components install` is
# disabled on a Homebrew-managed CLI -- so depending on them would mean either
# a broken script or modifying the operator's toolchain. The REST API is
# always available and needs nothing beyond the token gcloud already has.
API="https://monitoring.googleapis.com/v3/projects/$PROJECT_ID"
api() {  # api <METHOD> <PATH> [json-body]
    local method="$1" path="$2" body="${3:-}"
    local args=(-sS -X "$method" -H "Authorization: Bearer $(gcloud auth print-access-token)")
    [[ -n "$body" ]] && args+=(-H "Content-Type: application/json" -d "$body")
    curl "${args[@]}" "$API/$path"
}

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

# Extract one field from a JSON stream. Kept as a file-based helper because an
# inline python -c containing { } is subject to bash BRACE EXPANSION, which
# silently rewrites the program before python ever sees it.
cat > "$TMP/pick.py" <<'PYEOF'
import json, sys
kind, want = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else None)
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
if kind == "channel":
    for c in d.get("notificationChannels", []):
        if c.get("type") == "email" and c.get("labels", {}).get("email_address") == want:
            print(c["name"])
            break
elif kind == "policies":
    for p in d.get("alertPolicies", []):
        print(p.get("displayName", ""))
elif kind == "name":
    print(d.get("name", ""))
PYEOF

say "Ensuring email notification channel"
CHANNEL="$(api GET notificationChannels | python3 "$TMP/pick.py" channel "$ALERT_EMAIL")"

if [[ -z "$CHANNEL" && $DRY_RUN -eq 0 ]]; then
    cat > "$TMP/channel.json" <<JSON
{"type":"email","displayName":"Ecowitt alerts",
 "labels":{"email_address":"$ALERT_EMAIL"},"enabled":true}
JSON
    CHANNEL="$(api POST notificationChannels "@$TMP/channel.json" | python3 "$TMP/pick.py" name)"
fi
[[ -n "$CHANNEL" || $DRY_RUN -eq 1 ]] || { echo "ERROR: could not create notification channel" >&2; exit 1; }
echo "  channel: ${CHANNEL:-<dry-run>}"

# --- alert policies -------------------------------------------------------

# 1. DEAD MAN'S SWITCH. Fires when heartbeats stop arriving at all.
cat > "$TMP/absent.json" <<JSON
{
  "displayName": "Ecowitt: pipeline is not reporting",
  "documentation": {
    "content": "No heartbeat from ecowitt-db for ${ABSENCE_DURATION}. The VM, the systemd timer, or Cloud Logging access has failed. Nothing will alert about stale data because nothing is running.\\n\\nCheck: gcloud compute ssh ecowitt-db --zone=us-central1-a --tunnel-through-iap --command='systemctl list-timers ecowitt-*'",
    "mimeType": "text/markdown"
  },
  "conditions": [{
    "displayName": "No heartbeat for ${ABSENCE_DURATION}",
    "conditionAbsent": {
      "filter": "resource.type=\"global\" AND metric.type=\"logging.googleapis.com/user/ecowitt_heartbeat\"",
      "duration": "${ABSENCE_DURATION}",
      "aggregations": [{"alignmentPeriod": "300s", "perSeriesAligner": "ALIGN_COUNT"}]
    }
  }],
  "combiner": "OR",
  "enabled": true,
  "notificationChannels": ["${CHANNEL}"]
}
JSON

# 2. Alive but stale.
cat > "$TMP/unhealthy.json" <<JSON
{
  "displayName": "Ecowitt: pipeline reporting unhealthy",
  "documentation": {
    "content": "heartbeat.sh reported a problem: a stale successful run, a stale backup, or a run wedged in 'running'. The jsonPayload.problems field names which.\\n\\nCheck: gcloud logging read 'logName=\\"projects/${PROJECT_ID}/logs/${LOG_NAME}\\" AND severity=ERROR' --limit=5",
    "mimeType": "text/markdown"
  },
  "conditions": [{
    "displayName": "Unhealthy heartbeat observed",
    "conditionThreshold": {
      "filter": "resource.type=\"global\" AND metric.type=\"logging.googleapis.com/user/ecowitt_heartbeat_unhealthy\"",
      "comparison": "COMPARISON_GT",
      "thresholdValue": 0,
      "duration": "0s",
      "aggregations": [{"alignmentPeriod": "300s", "perSeriesAligner": "ALIGN_COUNT"}]
    }
  }],
  "combiner": "OR",
  "enabled": true,
  "notificationChannels": ["${CHANNEL}"]
}
JSON

say "Creating alert policies"
EXISTING="$(api GET alertPolicies | python3 "$TMP/pick.py" policies || true)"

for policy in absent unhealthy; do
    name="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["displayName"])' "$TMP/$policy.json")"
    if grep -Fxq "$name" <<<"$EXISTING"; then
        echo "  '$name' exists"
    elif [[ $DRY_RUN -eq 1 ]]; then
        echo "  [dry-run] create policy '$name'"
    else
        result="$(api POST alertPolicies "@$TMP/$policy.json" 2>/dev/null \
            || curl -sS -X POST -H "Authorization: Bearer $(gcloud auth print-access-token)" \
                    -H "Content-Type: application/json" --data-binary "@$TMP/$policy.json" \
                    "$API/alertPolicies")"
        if grep -q '"name"' <<<"$result"; then
            echo "  created '$name'"
        else
            echo "  FAILED '$name': $(head -c 300 <<<"$result")" >&2
            exit 1
        fi
    fi
done

say "Done."
cat <<EOF

Two policies, covering two different silences:
  1. "pipeline is not reporting"   -> fires on ABSENCE of heartbeats (box dead)
  2. "pipeline reporting unhealthy" -> fires on ERROR heartbeats (stale data)

Alerts go to: $ALERT_EMAIL  (confirm the subscription in your inbox)

Test the dead-man's switch honestly — stop the timer and wait:
  gcloud compute ssh ecowitt-db --zone=us-central1-a --tunnel-through-iap \\
    --command='sudo systemctl stop ecowitt-heartbeat.timer'
  # expect an email after ~${ABSENCE_DURATION}; then start it again
EOF
