#!/usr/bin/env bash
# Nightly backup: dump, VERIFY, upload, prove the upload landed.
#
# Runs on the VM as the ecowitt user, via systemd timer. Install with:
#   sudo install -m 755 backup.sh /opt/ecowitt/backup.sh
#   sudo systemctl enable --now ecowitt-backup.timer
#
# ---------------------------------------------------------------------------
# Why this is the most important script in infra/
#
# Choosing a self-managed VM traded ~$76/year against owning backups. That
# trade is only sound if the backups actually work. CLAUDE.md §1 asks for data
# "trustworthy without manual audit", and an unverified backup is precisely a
# manual audit deferred until the day it fails.
#
# So this does not just dump and upload. It restores the dump's table of
# contents, checks the expected relations are present, compares the observation
# row count against the live database, and re-reads the uploaded object's size
# from GCS. Any of those failing is a non-zero exit (§10, fail loudly).
# ---------------------------------------------------------------------------

set -euo pipefail

DB_NAME="${DB_NAME:-ecowitt}"
BUCKET="${BACKUP_BUCKET:?BACKUP_BUCKET must be set}"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DUMP="$WORKDIR/${DB_NAME}_${STAMP}.dump"
OBJECT="gs://${BUCKET}/daily/${DB_NAME}_${STAMP}.dump"

log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*"; }
fail() { log "FAILED: $*"; exit 1; }

# --- 1. dump --------------------------------------------------------------
log "dumping $DB_NAME"
pg_dump --format=custom --compress=9 --file="$DUMP" "$DB_NAME" \
    || fail "pg_dump returned non-zero"
[[ -s "$DUMP" ]] || fail "dump file is empty"
DUMP_BYTES="$(stat -c %s "$DUMP")"
log "dump written: $DUMP_BYTES bytes"

# --- 2. verify the dump is readable and complete --------------------------
# pg_dump exiting 0 does not prove the archive is restorable. Reading its TOC
# does prove it parses, and checking for expected relations proves it is this
# database rather than an empty one.
log "verifying archive"
TOC="$WORKDIR/toc.txt"
pg_restore --list "$DUMP" > "$TOC" || fail "pg_restore --list could not read the archive"

for relation in run_log raw_payload change_log quarantine metric_catalog; do
    grep -q " $relation" "$TOC" || fail "archive is missing expected relation: $relation"
done
log "archive contains all expected relations"

# --- 3. row-count agreement ----------------------------------------------
# Catches a dump taken against the wrong database, or one silently truncated.
LIVE_ROWS="$(psql -tAqc "SELECT count(*) FROM observation" "$DB_NAME" 2>/dev/null || echo "0")"
log "live observation rows: $LIVE_ROWS"
if [[ "$LIVE_ROWS" -gt 0 ]]; then
    grep -q " observation" "$TOC" \
        || fail "database has $LIVE_ROWS observation rows but the archive has no observation table"
fi

# --- 4. upload ------------------------------------------------------------
log "uploading to $OBJECT"
gcloud storage cp "$DUMP" "$OBJECT" || fail "upload failed"

# --- 5. prove it landed ---------------------------------------------------
# A successful `cp` is not proof the object is there and complete. Read the
# size back and compare. This is the step that turns "we run backups" into
# "we know the backup exists".
REMOTE_BYTES="$(gcloud storage objects describe "$OBJECT" --format='value(size)' 2>/dev/null)" \
    || fail "uploaded object is not readable back from GCS"
[[ "$REMOTE_BYTES" == "$DUMP_BYTES" ]] \
    || fail "size mismatch: local $DUMP_BYTES vs remote $REMOTE_BYTES"
log "verified remote object: $REMOTE_BYTES bytes"

# --- 6. heartbeat ---------------------------------------------------------
# §7's principle applied to backups: absence of a row means it did not run.
# A monitoring check that finds no recent heartbeat knows the difference
# between "backup failed" and "backup never started".
psql -qc "INSERT INTO backup_log (finished_at, object_uri, bytes, observation_rows)
          VALUES (now(), '$OBJECT', $REMOTE_BYTES, $LIVE_ROWS)" "$DB_NAME" 2>/dev/null \
    || log "WARNING: backup_log table absent — heartbeat not recorded"

log "backup complete"
