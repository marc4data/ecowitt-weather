#!/usr/bin/env bash
# Provision the Phase 1 BigQuery dataset and tables.
#
# Written as a script rather than console clicks so the choices are reviewable
# in git and the setup is repeatable. Safe to re-run: the dataset check is
# explicit and every DDL statement uses CREATE ... IF NOT EXISTS.
#
#   ./infra/create_bigquery.sh --dry-run
#   ./infra/create_bigquery.sh                 # defaults to option A (long)
#   SHAPE=wide ./infra/create_bigquery.sh
#
# Prerequisites you must do interactively (OAuth cannot run unattended):
#   gcloud auth login
#   gcloud config set project YOUR_PROJECT_ID

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
LOCATION="${LOCATION:-us-central1}"
DATASET="${DATASET:-ecowitt}"
SHAPE="${SHAPE:-long}"          # long | wide

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

say() { printf '\n==> %s\n' "$*"; }
run() {
    if [[ $DRY_RUN -eq 1 ]]; then printf '  [dry-run] %s\n' "$*"; else "$@"; fi
}

case "$SHAPE" in
    long) SHAPE_FILE="schema/option_a_long.sql" ;;
    wide) SHAPE_FILE="schema/option_b_wide.sql" ;;
    *) echo "ERROR: SHAPE must be 'long' or 'wide', got '$SHAPE'" >&2; exit 2 ;;
esac

# --- preflight ------------------------------------------------------------
if [[ -z "$PROJECT_ID" ]]; then
    echo "ERROR: no project set. Run: gcloud config set project YOUR_PROJECT_ID" >&2
    exit 2
fi
if ! gcloud auth list --filter=status:ACTIVE --format='value(account)' | grep -q .; then
    echo "ERROR: no active gcloud account. Run: gcloud auth login" >&2
    exit 2
fi
for f in schema/00_common.sql "$SHAPE_FILE" schema/assertions.sql; do
    [[ -f "$f" ]] || { echo "ERROR: missing $f (run from the repo root)" >&2; exit 2; }
done

say "Project $PROJECT_ID · location $LOCATION · dataset $DATASET · shape $SHAPE"

# --- API ------------------------------------------------------------------
say "Enabling BigQuery API (no-op if already enabled)"
run gcloud services enable bigquery.googleapis.com --project="$PROJECT_ID"

# --- dataset --------------------------------------------------------------
# The dataset's location is permanent -- it cannot be changed later without
# recreating and reloading, so it is worth getting right the first time.
if bq --project_id="$PROJECT_ID" show --dataset "$DATASET" >/dev/null 2>&1; then
    say "Dataset $DATASET already exists — skipping creation"
    existing="$(bq --project_id="$PROJECT_ID" --format=prettyjson show \
        --dataset "$DATASET" | grep -o '"location": "[^"]*"' | head -1)"
    echo "  existing $existing (immutable; must match $LOCATION)"
else
    say "Creating dataset $DATASET in $LOCATION"
    run bq --project_id="$PROJECT_ID" --location="$LOCATION" mk \
        --dataset \
        --description="Ecowitt weather pipeline" \
        "$DATASET"
fi

# --- tables ---------------------------------------------------------------
say "Applying schema/00_common.sql"
run bq --project_id="$PROJECT_ID" --location="$LOCATION" query \
    --use_legacy_sql=false --nouse_cache < schema/00_common.sql

say "Applying $SHAPE_FILE"
run bq --project_id="$PROJECT_ID" --location="$LOCATION" query \
    --use_legacy_sql=false --nouse_cache < "$SHAPE_FILE"

# --- assertions -----------------------------------------------------------
# Run once now to prove the suite executes. On empty tables every assertion
# should pass trivially -- that is the point: a suite that errors on an empty
# dataset would never be trusted enough to keep in the load path.
say "Smoke-running assertions.sql against the empty dataset"
if [[ $DRY_RUN -eq 1 ]]; then
    echo "  [dry-run] bq query < schema/assertions.sql"
elif bq --project_id="$PROJECT_ID" --location="$LOCATION" query \
        --use_legacy_sql=false --nouse_cache < schema/assertions.sql; then
    echo "  assertions passed on the empty dataset"
else
    echo "  WARNING: assertions failed on an empty dataset — fix before loading" >&2
fi

say "Done."
cat <<EOF

Dataset: $PROJECT_ID:$DATASET ($LOCATION), shape=$SHAPE

Next:
  1. Populate metric_catalog from samples/reports/metric_catalog.md.
     Nothing may be loaded before it -- assertions 4 and 5 depend on it.
  2. Build the Phase 1 ingestion job.
  3. Wire assertions.sql into the job so a failure marks the run failed and
     exits non-zero. Assertions are the only thing standing in for the
     constraints BigQuery does not have.

Cost check (should read ~0 B for a while):
  bq --project_id=$PROJECT_ID show --dataset $DATASET
EOF
