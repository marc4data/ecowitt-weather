#!/usr/bin/env bash
# Wrapper: fetch credentials from Secret Manager into the environment, then run.
#
# Secrets reach the process through env vars and never touch disk (§10). They
# are also never echoed -- `set -x` here would defeat the entire arrangement.
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null || echo ecowitt-504320)}"
secret() { gcloud secrets versions access latest --secret="$1" --project="$PROJECT_ID"; }

ECOWITT_APPLICATION_KEY="$(secret ecowitt-application-key)"
ECOWITT_API_KEY="$(secret ecowitt-api-key)"
ECOWITT_MAC="$(secret ecowitt-mac)"
export ECOWITT_APPLICATION_KEY ECOWITT_API_KEY ECOWITT_MAC
export ECOWITT_DSN="${ECOWITT_DSN:-dbname=ecowitt}"

cd /opt/ecowitt/app
# --raw-dir is a top-level flag and must precede the subcommand.
exec ./venv/bin/python -m ingest --raw-dir /opt/ecowitt/raw "$@"
