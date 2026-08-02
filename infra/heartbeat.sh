#!/usr/bin/env bash
# Heartbeat — detects a silently dead pipeline.
#
# CLAUDE.md §10 names a silently dead scheduled job as the primary risk to this
# project. Moving the job onto this VM removed Cloud Scheduler, whose failures
# were visible in the GCP console; a systemd timer that stops firing is silent.
# This is what replaces that visibility.
#
# It covers two DIFFERENT failure modes, and they need different mechanisms:
#
#   1. "The box is alive but something is stale."  Detected here: no recent
#      successful run, no recent backup, or a run wedged in 'running'. Emits an
#      ERROR log entry, which a Cloud Monitoring alert policy watches for.
#
#   2. "The box is dead."  CANNOT be detected here -- a dead VM runs nothing
#      and reports nothing. That is why this emits a log entry on EVERY run,
#      healthy or not: Cloud Monitoring alerts on the *absence* of those
#      entries. Silence is the signal. See infra/create_monitoring.sh.
#
# A monitor that only reports problems cannot distinguish "healthy" from
# "dead", which is exactly the distinction §7 says matters.

set -uo pipefail

DB_NAME="${DB_NAME:-ecowitt}"
LOG_NAME="${LOG_NAME:-ecowitt-heartbeat}"

# Pull cadence is still an open decision (CLAUDE.md §11). Until it is settled,
# 2h is a deliberately loose threshold: it catches a stopped pipeline without
# firing on a single missed pull. Tighten it once cadence is chosen.
MAX_RUN_AGE_MIN="${MAX_RUN_AGE_MIN:-120}"
MAX_BACKUP_AGE_MIN="${MAX_BACKUP_AGE_MIN:-1560}"   # 26h — one nightly + slack
MAX_RUNNING_MIN="${MAX_RUNNING_MIN:-60}"           # a run stuck this long crashed

q() { psql -tAqc "$1" "$DB_NAME" 2>/dev/null || echo ""; }

# Ages in minutes. NULL (never happened) is reported as -1 and treated as
# unhealthy, because "never ran" and "ran long ago" are both failures — but
# they are distinguishable in the payload, which matters when diagnosing.
RUN_AGE="$(q "SELECT coalesce(round(extract(epoch from now()-max(started_at))/60), -1)
              FROM run_log WHERE status='succeeded'")"
BACKUP_AGE="$(q "SELECT coalesce(round(extract(epoch from now()-max(finished_at))/60), -1)
                 FROM backup_log")"
STUCK="$(q "SELECT count(*) FROM run_log
            WHERE status='running' AND started_at < now() - interval '$MAX_RUNNING_MIN minutes'")"
OBS_ROWS="$(q "SELECT count(*) FROM observation")"
LAST_OBS_AGE="$(q "SELECT coalesce(round(extract(epoch from now()-max(ts_utc))/60), -1)
                   FROM observation")"

RUN_AGE="${RUN_AGE:--1}"; BACKUP_AGE="${BACKUP_AGE:--1}"
STUCK="${STUCK:-0}"; OBS_ROWS="${OBS_ROWS:-0}"; LAST_OBS_AGE="${LAST_OBS_AGE:--1}"

PROBLEMS=()
if ! pg_isready -q; then
    PROBLEMS+=("postgres_not_accepting_connections")
fi
# -1 means "never happened". Before the first ingestion run exists that is
# expected rather than broken, so only flag it once observations are present.
if [[ "$RUN_AGE" == "-1" && "$OBS_ROWS" -gt 0 ]]; then
    PROBLEMS+=("no_successful_run_ever")
elif [[ "$RUN_AGE" != "-1" && "$RUN_AGE" -gt "$MAX_RUN_AGE_MIN" ]]; then
    PROBLEMS+=("last_successful_run_${RUN_AGE}min_ago")
fi
if [[ "$BACKUP_AGE" == "-1" && "$OBS_ROWS" -gt 0 ]]; then
    PROBLEMS+=("no_backup_ever_but_data_exists")
elif [[ "$BACKUP_AGE" != "-1" && "$BACKUP_AGE" -gt "$MAX_BACKUP_AGE_MIN" ]]; then
    PROBLEMS+=("last_backup_${BACKUP_AGE}min_ago")
fi
if [[ "$STUCK" -gt 0 ]]; then
    PROBLEMS+=("${STUCK}_runs_wedged_in_running")
fi

if [[ ${#PROBLEMS[@]} -eq 0 ]]; then
    SEVERITY="INFO"; STATUS="healthy"; DETAIL=""
else
    SEVERITY="ERROR"; STATUS="unhealthy"
    DETAIL="$(IFS=,; echo "${PROBLEMS[*]}")"
fi

PAYLOAD=$(cat <<JSON
{"status":"$STATUS","problems":"$DETAIL",
 "last_run_age_min":$RUN_AGE,"last_backup_age_min":$BACKUP_AGE,
 "runs_wedged":$STUCK,"observation_rows":$OBS_ROWS,
 "last_observation_age_min":$LAST_OBS_AGE}
JSON
)

# Emitted on EVERY invocation, healthy or not. The absence of these entries is
# what tells Cloud Monitoring the machine is gone.
gcloud logging write "$LOG_NAME" "$PAYLOAD" \
    --payload-type=json --severity="$SEVERITY" 2>/dev/null \
    || echo "WARNING: could not write to Cloud Logging (heartbeat is blind)" >&2

echo "$STATUS run_age=${RUN_AGE}m backup_age=${BACKUP_AGE}m wedged=$STUCK rows=$OBS_ROWS"
[[ "$STATUS" == "healthy" ]] || exit 1
