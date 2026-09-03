# ecowitt_weather

Moves Ecowitt weather station data into a persistent database with a logical
schema, accurately and observably. See [CLAUDE.md](CLAUDE.md) for goals and
constraints.

**Current phase: 0 — endpoint discovery.** No database, no pipeline. This phase
produces sample files and reports so that schema design is based on observed
data rather than inference. Requirements:
[00_DISCOVERY_REQUIREMENTS.md](00_DISCOVERY_REQUIREMENTS.md).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
# then fill in ECOWITT_APPLICATION_KEY, ECOWITT_API_KEY, ECOWITT_MAC
```

`.env` is gitignored and must never be committed.

### Getting the console MAC

Read it off the HP2560's Weather Server page. Alternatively try:

```bash
python -m discovery devices
```

That calls an endpoint not documented in `CLAUDE.md` §5.1 and may not exist —
it reports what happened either way.

## Commands

```bash
python -m discovery check      # verify credentials with one real_time call
python -m discovery devices    # attempt to recover the MAC from the account

ruff check . && ruff format --check .
pytest
```

Not yet implemented: `probe` (D2), `sample`/`inventory` (D3), `units` (D4).

## Output

| Path | Committed? | Contents |
|---|---|---|
| `samples/raw/` | no | verbatim API responses + `.meta.json` sidecars |
| `samples/reports/` | **yes** | D2–D5, the Phase 0 deliverable |

Captures are additive — filenames are UTC-timestamped, so re-running never
overwrites a prior sample.

Credentials are redacted from every URL written to disk. The MAC is *not*
redacted in `samples/raw/` (gitignored, and captures need to stay
interpretable), so report generators must never echo it into
`samples/reports/`, which is committed.
