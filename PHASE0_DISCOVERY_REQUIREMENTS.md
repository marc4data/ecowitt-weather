# Phase 0 — Discovery Requirements

**Project:** Ecowitt weather data pipeline
**Phase:** 0 of 4 (see `CLAUDE.md` §2)
**Status:** ready to implement

---

## 1. Purpose

Establish empirically what the Ecowitt Cloud API v3 actually returns for **this
station**, so that schema design in Phase 1 is based on observed data rather than
inference.

Nothing about the data shape is currently known. Response structure, field names,
sensor coverage, units, null behavior, and granularity behavior are all
unverified. The reference implementation (`CLAUDE.md` §5.1–5.2) provides a
hypothesis about request construction and response shape; this phase confirms or
refutes it.

## 2. Explicitly out of scope

Do not build any of the following in Phase 0. If a task seems to require one,
stop and ask.

- Database connections, DDL, migrations, ORM models, or dataclasses
- Any table shape decision (long vs. wide)
- The ingestion pipeline, scheduling, or upsert logic
- `run_log` / `change_log` implementation
- Resampling, reconciliation, or gap-fill logic
- Retry/backoff frameworks, abstraction layers, plugin architectures

This phase produces **sample files and a report**. It is throwaway-adjacent code:
the request-construction portion will likely be carried into Phase 1, the rest
will not.

## 3. Definition of done

Phase 0 is complete when all of the following exist and have been reviewed by the
user:

| # | Artifact | Path | Status |
|---|---|---|---|
| D1 | Raw response samples, verbatim | `samples/raw/` | ✅ accumulating |
| D2 | Granularity probe results | `samples/reports/granularity.md` | ✅ done 2026-08-02 |
| D3 | Field inventory | `samples/reports/field_inventory.md` | ✅ done 2026-08-02 |
| D4 | Observed API behavior notes | `samples/reports/api_behavior.md` | ✅ done 2026-08-02 |
| D5 | Written recommendation on table shape | `samples/reports/findings.md` | ✅ awaiting your review |

**Schema design does not begin until the user has reviewed these.**

## 4. Environment and tooling

Defaults chosen for speed; change if the user says otherwise.

| Decision | Value |
|---|---|
| Runs on | Local workstation. Not cloud, not containerized. |
| Python | 3.11+ |
| Dependency manager | stdlib `venv` + `pip` (decided 2026-08-01; `uv` not installed) |
| Lint/format | `ruff` |
| Tests | `pytest` — minimal in this phase |
| HTTP | `requests` |
| Config | `python-dotenv` |

### Repository layout

```
.
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── .env.example          # committed
├── .env                  # gitignored, never committed
├── .gitignore
├── src/
│   └── discovery/
│       ├── client.py     # request construction, no business logic
│       ├── probe.py      # granularity probe (§6)
│       ├── inventory.py  # field inventory (§7)
│       └── __main__.py   # CLI entry
└── samples/
    ├── raw/              # gitignored
    └── reports/          # COMMITTED — D2–D5 are the deliverable
```

**Amended 2026-08-01:** `samples/` is no longer gitignored in its entirety.
`samples/raw/` is ignored (large, regenerable, credential-adjacent metadata);
`samples/reports/` is committed, because D2–D5 are what drive Phase 1 schema
design and must be reviewable in history.

### Secrets

Credentials already exist (ecowitt.net account, Application Key, API Key).

- Read from `.env` via `python-dotenv`: `ECOWITT_APPLICATION_KEY`,
  `ECOWITT_API_KEY`, `ECOWITT_MAC`
- `.env` is gitignored. `.env.example` contains the key names with empty values.
- **Never** write credentials into source, defaults, test fixtures, log output,
  or saved sample files. Redact them from any captured request URL.
- Fail with a clear message if any variable is missing. Do not prompt
  interactively and do not fall back to a default.
- The MAC is identifying but not a credential. It stays readable in
  `samples/raw/` so captures remain interpretable; report generators must never
  echo it into `samples/reports/`, which is committed.

## 5. Raw sample capture (D1)

Every API response is written to disk **verbatim, before any parsing**.

- Filename: `samples/raw/{endpoint}_{param_summary}_{utc_timestamp}.json`
- Alongside each, a `.meta.json` recording: full request URL **with credentials
  redacted**, HTTP status, response headers, wall-clock duration, and the UTC
  time of the request.
- If parsing fails, the raw file must still exist. Capture first, parse second.

## 6. Granularity probe (D2) — highest priority

This resolves the open risk in `CLAUDE.md` §6 and determines how backfill must
work. **Do this before the field inventory.**

`cycle_type` accepts `auto`, `5min`, `30min`, `4hour`, `1day`. The question is
not whether `5min` can be requested — it can — but **whether it is honored**, and
what happens when it is not.

Run the full cross product of:

- **`cycle_type`**: `5min`, `auto`
- **Span**, all ending at the most recent complete hour: 1 h, 6 h, 24 h, 48 h,
  7 d, 30 d, 90 d

Run spans in ascending order. If `5min` stops being honored at 7 d, that is known
before the 90 d request — the largest and slowest cell — is issued.

Then three retention probes with `cycle_type=5min`, each a 24-hour window:

- ~30 days ago
- ~100 days ago (just past the stated 3-month/5-min boundary)
- ~400 days ago (past the stated 1-year/30-min boundary)

⚠️ These are only interpretable if the station has been reporting that long.
Record the station's first-report date (`CLAUDE.md` §4) alongside the results; an
empty response from the 400-day probe otherwise cannot be distinguished from an
API retention limit.

For each request, record in `granularity.md`:

| Field | Notes |
|---|---|
| `cycle_type` requested | |
| Span requested | |
| HTTP status | |
| API `code` field | non-zero means failure regardless of HTTP 200 |
| Point count returned | |
| Median timestamp delta | in seconds |
| Min / max timestamp delta | reveals irregularity |
| Delta matches request? | yes / no |
| Response size, duration | |

**The finding that matters most:** when `5min` is not honored, does the API
*reject* the request or *silently return coarser data*? Silent downgrade is the
dangerous case — it yields data that looks complete at the wrong resolution.

Conclude with an explicit statement of the **maximum span for which
`cycle_type=5min` is reliably honored**. That number becomes the backfill chunk
size in Phase 1.

## 7. Field inventory (D3)

Call `/device/real_time` with `call_back=all`. **History rejects `all`**
(`code=40016`) — pass the explicit group list instead, and frame the window in
console-local time or it returns empty with `code=0`. See `CLAUDE.md` §5.0.

Take at least 3 real-time samples spaced ≥5 minutes apart, and at least one
24-hour history sample.

Produce a table covering every field observed:

| Column | Meaning |
|---|---|
| Field path | dotted, e.g. `data.outdoor.temperature` |
| Endpoint(s) | real-time, history, or both |
| Raw type | as it arrives — likely string even for numbers |
| Example values | 2–3 actual values |
| Unit reported | verbatim, including encoding (e.g. `℃`) |
| Null / missing rate | across all samples |
| Parses as float? | flag anything that does not |

Also record separately:

- **Which sensors this station actually reports.** Compare against the HP2560's
  supported sensor list; note anything present in the response that is not a real
  attached sensor (placeholder or zero-filled channels).
- **Fields present in one endpoint but not the other.**
- **Structural differences** between real-time and history shapes, confirming or
  correcting `CLAUDE.md` §5.2.
- **Any field whose name or meaning is ambiguous**, flagged for the user.

## 8. Unit verification (part of D4)

Units are request parameters, not just console settings.

- Send explicit unit IDs (`temp_unitid`, `pressure_unitid`, `wind_speed_unitid`,
  `rainfall_unitid`, `solar_irradiance_unitid`) per
  `doc.ecowitt.net/web/#/apiv3en?page_id=17`.
- Record whether the returned `unit` string matches what was requested, for every
  metric.
- Test at least two different unit IDs for temperature to confirm the parameter
  is actually honored.
- Note the exact unit strings returned, including character encoding — these will
  become stored values and must round-trip cleanly.

✅ **Resolved 2026-08-02, without the doc.** `python -m discovery units`
discovers each parameter's valid range from the API's own error message, sweeps
it, and records the exact unit string every ID produces. Results in
`samples/reports/api_behavior.md`; mapping mirrored into `CLAUDE.md` §5.1.

## 9. API behavior notes (D4)

Record whatever is observed, without deliberately stress-testing:

- Error codes encountered and what triggers them
- Behavior on invalid MAC, bad date range, future dates, `end_date` before
  `start_date`
- Any rate-limiting response, and any documented limit found in the docs
- Timestamp format and timezone semantics — **is the returned epoch UTC or
  console-local?** Compare a known observation time against the console display.
  This determines the conversion in Phase 1 and is easy to get silently wrong.

  A machine-side check runs first: every capture's `.meta.json` records
  `requested_at_epoch`. Diff that against the `time` field on a real-time leaf.
  Offset ≈ 0 → the epoch is true UTC. A whole-hour offset matching the console's
  timezone → console-local time is being emitted as though it were an epoch,
  which is the silent-corruption case. The console comparison confirms whichever
  the diff suggests.
- Maximum span the history endpoint accepts before erroring
- Whether `call_back=all` genuinely returns everything, or whether some fields
  require explicit selection

## 10. Findings and recommendation (D5)

A short document, written for the user, containing:

1. Whether the `CLAUDE.md` §5.1–5.2 hypotheses held
2. The maximum reliable `5min` span, stated as a number
3. Whether silent downgrade occurs, and how to detect it at runtime
4. A recommendation on **table shape** (long vs. wide) with reasoning grounded in
   the observed response structure and the sensor count
5. Any field requiring a user decision before schema design
6. Anything surprising

## 11. Implementation constraints

- **UTC everywhere.** Use `datetime.fromtimestamp(t, tz=timezone.utc)`. Never
  the naive form.
- **No unconditional casts.** A value that fails to parse is recorded as a
  parse failure in the inventory, not an exception.
- **Non-zero exit on failure.** A discovery run that could not complete must exit
  non-zero with a clear message.
- **Be polite to the API.** Sequential requests, a small delay between them. No
  concurrency in this phase.
- **Idempotent-ish.** Re-running must not overwrite prior samples — timestamped
  filenames.
- Keep it simple. Roughly 300–500 lines total is the expected size. If the design
  is growing past that, stop and ask.

## 12. Open questions for the user (post-review)

These are deliberately unanswered and must not be guessed:

- [x] Database target — **BigQuery**, us-central1 (2026-08-02)
- [x] Where the Phase 1 job runs — **Cloud Run job + Cloud Scheduler** (2026-08-02)
- [ ] Pull cadence
- [ ] Whether to bootstrap historical data, accepting mixed resolution
- [ ] Resample interval and gap-fill policy
- [ ] Reconciliation window and cadence
