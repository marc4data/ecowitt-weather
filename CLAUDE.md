# CLAUDE.md

Persistent context for Claude Code working in this repository.

> **Status: pre-implementation.** The schema is not yet known — see §3. Sections
> marked `TBD` are unresolved. **Do not invent answers for them.** If a task
> depends on an unresolved item, stop and ask.

---

## 1. Goal

A **simple, reliable Python utility** that moves Ecowitt weather station data into
a persistent database with a logical schema, and does so accurately, repeatably,
and observably.

It owns *all* data movement and transformation for this system. Everything
downstream reads from what this tool produces.

Design values, in priority order:

1. **Correctness** — data in the store must be trustworthy without manual audit.
2. **Reliability** — unattended operation; failures are loud, not silent.
3. **Simplicity** — the smallest thing that satisfies 1 and 2. Resist frameworks,
   abstraction layers, and cleverness. This is a data pipeline, not a platform.
4. **Observability** — every run and every change is logged and queryable.

### In scope

- Extraction from Ecowitt (see §5)
- Landing raw payloads immutably
- Normalization, unit handling, resampling to a fixed time grid
- Idempotent loading — **write only when something actually changed**
- Reconciliation passes that re-verify stored data against source
- Derived tables and views for reporting and analytics
- Run logging and change logging (§7)

### Not in scope

- Any dashboard or UI. Visualization is a separate concern reading from this DB.
- Weather-condition alerting (this is not a warning system)
- Model training or serving — this tool prepares the substrate, nothing more

## 2. Roadmap

| Phase | Scope |
|---|---|
| **0** | **Endpoint discovery and schema design** — current phase, see §3 |
| **1** | Ecowitt weather ingestion — persistent store, instrumented |
| **2** | Analytic/reporting tables and views |
| **3** | Basement flooding data ingestion (source TBD) |
| **4** | Feature substrate for predictive modeling — flooding is the target variable |

Phase 4 is why point-in-time correctness matters from day one (§8). Do not defer it.

## 3. ⚠️ Schema is UNKNOWN — discovery comes first

**Nothing about the data shape has been established.** Ecowitt's API response
structure, field names, units, null behavior, and which sensors report have not
been observed.

**The first deliverable is a discovery script, not a pipeline.** It should:

- Call `/device/real_time` with `call_back=all`. **History rejects `all`** —
  use an explicit group list (see §5.0)
- Persist raw responses verbatim to disk as dated samples (gitignored)
- Emit an inventory: every field observed, its type, example values, null rate,
  which sensors appear, what units are reported
- Probe the `cycle_type` granularity question in §6 empirically — vary span
  against `cycle_type=5min` and record the returned timestamp spacing
- Record observed API error codes and any rate-limiting behavior

Schema design happens *after* reviewing those samples with the user. Do not write
DDL, ORM models, or dataclasses before then.

## 4. Hardware and source

| Item | Value |
|---|---|
| Console | Ecowitt HP2560 (7" TFT receiver) |
| Console MAC | ✅ in `.env` as `ECOWITT_MAC` |
| Sensors attached | ✅ enumerated — see below |
| Reporting interval to cloud | Cloud stores at 5 min; console push interval still unconfirmed |
| Console history/SD interval | TBD (1–240 min, selectable) |
| ecowitt.net account | ✅ exists |
| Application Key / API Key | ✅ generated (Private Center) |
| Station first-report date | **2026-08-01** — the station is new |
| Console timezone | UTC−5 observed 2026-08-02. **Detect at runtime, never hardcode** |

Sensor groups observed in `/device/real_time` (42 leaf metrics):

| Group | Metrics |
|---|---|
| `outdoor` | temperature, feels_like, app_temp, dew_point, vpd, humidity |
| `indoor` | temperature, humidity, dew_point, feels_like, app_tempin |
| `solar_and_uvi` | solar, uvi |
| `rainfall_piezo` | rain_rate, daily, event, 1_hour, weekly, monthly, yearly |
| `wind` | wind_speed, wind_gust, wind_direction |
| `pressure` | relative, absolute |
| `temp_and_humidity_ch1/2/3` | temperature, humidity |
| `soil_ch1/2` | soilmoisture, ad |
| `battery` | haptic_array_battery, haptic_array_capacitor, 3× temp_humidity_sensor_chN, 2× soilmoisture_sensor_chN |

Rain is **piezo/haptic only** — there is no `rainfall` (tipping-bucket) group.
Requesting one returns `code=0` with empty data, not an error.

⚠️ **The station has ~1 day of history.** Every retention question in §6 is
unanswerable until it accumulates months. Do not mistake an empty window for an
API retention limit.

Credentials exist, so discovery (§3) is unblocked. The console MAC is still needed
as a request parameter — read it off the console's Weather Server page.

Note: the HP2560 pushes outbound only. It does **not** expose a local polling API.

## 5. Ingestion approach

**v1 is pull-based.** A scheduled Python job calls the Ecowitt Cloud API v3 and
loads results.

Rationale: no inbound network exposure, no always-on listener on the LAN, no
port-80 concerns, and it matches the upsert/change-detection model the tool
needs. The cloud retention ceiling (§6) is not binding as long as the job runs
frequently — pulling within the 5-minute-resolution window and storing locally
accumulates full-resolution history indefinitely.

- Base URL: `https://api.ecowitt.net/api/v3`
- Auth: Application Key + API Key, created in Private Center on ecowitt.net
- ⚠️ **DECISION NOT MADE:** whether to add a push listener later. Do not build for
  it speculatively, but do not make it structurally impossible either — keep
  ingestion adapters separable from load and transform.

Fallback path, not automated: the console writes basic *and* extra-sensor data to
a micro SD card (max 32 GB, FAT32) at the configured interval, exportable as CSV.
Useful for disaster recovery. Console internal memory holds basic data only.

### 5.0 ✅ Confirmed API behavior (observed 2026-08-02, Phase 0)

These supersede the hypotheses below wherever they conflict. Evidence:
`samples/reports/granularity.md` and the raw captures.

1. **`start_date` / `end_date` are interpreted in console-local time, but every
   returned epoch is UTC.** The input is local, the output is UTC — asymmetric.
   Framing a request in UTC returns `code=0` with an empty body: a silent miss,
   never an error. This is the single easiest way to corrupt a backfill.
   **Resolve the zone from `/device/info` (`probe.resolve_console_tz`)** — it
   returns `date_zone_id` as an IANA name, currently `America/Chicago`. Use the
   IANA zone, not a fixed offset: an offset is correct only until the next DST
   transition and is *already* wrong for any historical window straddling one,
   which is exactly what backfill does. Measuring the offset empirically is
   the fallback, and it carries no DST rules.
2. **`call_back=all` is rejected by `/device/history`** with `code=40016`
   (`"all is invalid"`). It works only on `/device/real_time`. History requires
   an explicit comma-separated group or field list.
3. **An unrecognised `call_back` group returns `code=0` with empty data.** A
   typo is indistinguishable from a sensor that reported nothing. Assert that
   requested groups actually came back.
4. **`cycle_type=5min` is honored up to a 24 h span and silently downgraded
   beyond it** — 48 h returns 30 min, 30 d returns 4 hour, all with `code=0`.
   Backfill chunk size is therefore **24 h**, and returned timestamp spacing
   must be verified on every response. The exact cutoff between 24 h and 48 h
   was not bisected; 24 h is used because it is both safe and natural.
5. **A 90 d span returns zero points**, not an error.
6. Real-time exposes **42** leaf metrics; history returns **39**. ✅ The three
   missing from history are identified: `battery.temp_humidity_sensor_ch1/2/3`,
   the unitless status codes. History carries every voltage battery field but
   drops the status ones.
8. **Gaps are routine.** A 24 h history capture returned 281 of an expected 289
   points — two dropouts totalling 8 missing 5-minute slots, on a healthy
   station. Gap detection needs a threshold or it will alarm constantly.
9. **All history metrics share one identical timestamp set** (281 stamps × 39
   metrics, no ragged edges), so pivoting long→wide is clean.
7. **`/device/info` and `/device/list` both exist** (neither is in §5.1) and are
   the answer to several questions:
   - `date_zone_id` — the console's IANA timezone, authoritative (see 1).
   - `mac` — recoverable from the account, so the console need not be read.
   - `createtime` — 2026-07-23, though history only reaches 2026-08-01.
     Registration date is **not** first-data date; do not use it as one.
   - `latitude` / `longitude` / `stationtype` (`EasyWeatherPro_V5.2.2`).
   - `last_update` — embeds the entire real-time payload, making `/device/info`
     a superset of `/device/real_time`.
   `device/setting`, `device/detail`, `device/unit`, and `user/info` all return
   `code=404`. **There is no API endpoint exposing the console's unit settings.**
   The console's unit configuration is visible only as the *default* units in a
   response that sends no unit parameters — which is precisely why §10 requires
   pinning unit IDs per request rather than trusting the console.

### 5.1 API mechanics

Derived from the reference implementation (§5.3) and its inline docs. Dates to
roughly 2022–23 — **treat as a hypothesis to confirm during discovery**, not as
current documentation. Where §5.0 contradicts this section, §5.0 wins.

Endpoints:

- `GET /device/real_time`
- `GET /device/history`

Common parameters: `application_key`, `api_key`, `mac`, `call_back`.

- `call_back` selects fields: `all`, or a comma-separated list such as
  `outdoor.temperature,indoor.temperature`. **Discovery uses `all`.**

History-only parameters: `start_date`, `end_date` (format `%Y-%m-%d %H:%M:%S`),
and `cycle_type`.

- `cycle_type` accepts `auto`, `5min`, `30min`, `4hour`, `1day` — granularity can
  be **requested explicitly** rather than inferred from span length. This is the
  key lever for backfill (§6).

Unit selection is per-request, not just a console setting:

```
&temp_unitid=..&pressure_unitid=..&wind_speed_unitid=..
&rainfall_unitid=..&solar_irradiance_unitid=..
```

✅ **ID values discovered empirically 2026-08-02** (`samples/reports/api_behavior.md`).
Not read from the docs — obtained by sending an out-of-range value and reading the
range back out of the API's own error message, then sweeping it:

| parameter | IDs | mapping |
|---|---|---|
| `temp_unitid` | 1–2 | 1 = `℃` (U+2103) · 2 = `ºF` (U+00BA) |
| `pressure_unitid` | 3–5 | 3 = `hPa` · 4 = `inHg` · 5 = `mmHg` |
| `wind_speed_unitid` | 6–11 | 6 = `m/s` · 7 = `km/h` · 8 = `knots` · 9 = `mph` · 10 = `BFT` · 11 = `fpm` |
| `rainfall_unitid` | 12–13 | 12 = `mm` / `mm/hr` · 13 = `in` / `in/hr` |
| `solar_irradiance_unitid` | 14–16 | 14 = `lx` · 15 = `fc` · 16 = `W/m²` |
| `capacity_unitid` | 24–26 | WFC/AC1100 sub-devices only; not observable here |

All five applicable parameters are genuinely honored. **IDs 17–23 are unaccounted
for**, so unit parameters exist that this project has not identified.

**Pin these explicitly in config, and assert that the returned `unit` matches what
was requested.** Do not accept whatever arrives — a silent unit change corrupts
history in a way that is very hard to detect later.

⚠️ **The API is not self-consistent about degree signs.** `temp_unitid=1` returns
`℃` (U+2103 DEGREE CELSIUS) but `temp_unitid=2` returns `ºF` (U+00BA MASCULINE
ORDINAL INDICATOR + `F`) — two conventions from one parameter. The published
example response also uses `℉` (U+2109) for a sub-device alongside `ºF` for the
main groups, and mixes `µ` (U+00B5) with `μ` (U+03BC). **Never normalise a unit
string.** Compare and store exact bytes.

Responses carry a `code` field. Check it; a 200 HTTP status does not imply success.

### 5.2 Response shapes (expected)

✅ **Both shapes confirmed 2026-08-02.** All 42 real-time leaves carry exactly
`{time, unit, value}`; history leaves carry `{unit, list}`.

**Real-time** — nested; leaf nodes carry value, unit, and time:

```
data.outdoor.temperature = {'time': '1785644149', 'unit': 'ºF', 'value': '78.3'}
```

**History** — unit stated once per metric, then a timestamp→value map:

```
data.outdoor.temperature = {'unit': 'ºF', 'list': {'1785644149': '78.3', ...}}
```

⚠️ **Unit encoding gotcha.** This account returns `ºF` — that is
**U+00BA MASCULINE ORDINAL INDICATOR**, not U+00B0 DEGREE SIGN, and not the
U+2103 `℃` this section originally guessed. Wind direction is bare `º`
(U+00BA). Solar is `W/m²` (U+00B2). Store unit strings as opaque bytes and
compare exactly; a `°`/`º` normalisation would silently rewrite history.
Empty-string units are used for dimensionless values (`uvi`, `soil_chN.ad`).

Observed units: `ºF`, `%`, `inHg`, `mph`, `in`, `in/hr`, `W/m²`, `V`, `º`, `''`.
Note `outdoor.vpd` reports in `inHg`.

Note the history shape is already effectively long/tall. A wide curated table
would mean pivoting against the source's natural format — weigh that when
deciding table shape (§11).

Numeric values arrive as **strings**. Cast defensively; do not assume every field
parses as a float.

### 5.3 Reference implementation — mechanics only

`github.com/pgarmyn/ecowitt_net` (~115 lines) is a useful reference for request
construction and response structure.

**Do not copy its patterns.** Four specific things in it violate this project's
requirements:

1. `datetime.fromtimestamp(t)` with no timezone — converts epoch to host-local
   time. Violates §10 (store UTC) and breaks across DST or on a retimed host.
   Use `datetime.fromtimestamp(t, tz=timezone.utc)`.
2. Unconditional `float()` on every value — raises on nulls or non-numerics.
   Quarantine instead (§10).
3. Exceptions swallowed into a return dict with `code: -1` plus a `print()`.
   A scheduled job would exit zero on total failure. Violates "fail loudly".
4. Credentials hardcoded in a committed source file. Violates §10.

## 6. Hard constraints

**Ecowitt cloud downsamples with age:**

| Age of data | Stored interval |
|---|---|
| Past 3 months | 5 min |
| Past 1 year | 30 min |
| Past 2 years | 4 hours |

**Returned granularity also varies with query span:**

| Query span | Returned interval |
|---|---|
| By day | 5 min |
| By week | 30 min |
| By month | 4 hours |
| By year | 1 day |

Consequences:

- The 5-minute window is a **rolling 3 months**. Fall behind and that resolution
  is gone permanently. Gap detection is therefore time-critical, not cosmetic.
- `cycle_type=5min` can be requested explicitly (§5.1), so granularity is not
  purely a function of span. But the reference implementation notes that valid
  values depend on timespan.
- ✅ **RESOLVED 2026-08-02 — and it is the bad outcome.** `cycle_type=5min` is
  honored to **24 h** and **silently downgraded** past it (48 h → 30 min,
  30 d → 4 hour), always with `code=0`. The API does not reject the request.
  Consequences, all mandatory for Phase 1:
  - Backfill chunks at **24 h**.
  - **Verify returned timestamp spacing on every response.** A response that
    claims success at the wrong resolution is indistinguishable from a correct
    one until you measure the deltas.
  - Never infer resolution from the request parameters.
- ⚠️ The **retention** tiers above remain **UNVERIFIED**. The station's history
  begins 2026-08-01, so every retention probe returned empty for lack of data
  rather than lack of retention. Re-probe once months have accumulated.
- The API doc site blocks automated fetching — open in a browser.

## 7. Instrumentation — required, not optional

Two tables, populated by every execution.

### `run_log`

`run_id` · trigger (scheduled / manual / backfill) · mode · window requested ·
started_at · ended_at · status · rows fetched / inserted / updated / unchanged /
rejected · error detail

A run that changed nothing still writes a row. Absence of a row means the job
didn't run — that distinction is the whole point.

### `change_log`

natural key · field · old value · new value · `run_id` · changed_at · reason

This is what makes "verify accurate production data" auditable rather than
aspirational, and it is the mechanism for point-in-time reconstruction (§8).

### Change detection

Compare before write — row hash or field-level diff. **Never issue a blind
upsert.** "Unchanged" must be a countable outcome, because a reconciliation run
that reports thousands of updates is a signal something is wrong.

## 8. Point-in-time correctness

Because flooding prediction (Phase 4) will use weather data as features, a
corrected historical value that silently overwrites the original creates training
data that was not available at prediction time. That is leakage, and it will not
be visible in model metrics until production.

Requirements:

- **Raw landing is append-only and immutable.** Never mutate a landed payload.
- The curated table plus `change_log` must be able to answer: *what did the
  record for timestamp T look like as of date D?*
- Corrections are recorded as changes, never as in-place overwrites without trace.

## 9. Resampling and reconciliation

Two distinct operations. Keep them separate in code and in the run log.

**Resample** — normalize observations onto a fixed time grid. Modeling requires a
regular grid; the source does not reliably provide one. Interpolation and
gap-fill rules are TBD and must be explicit, recorded per row, and never silently
applied. A synthesized value must be distinguishable from an observed one.

⚠️ **The resampling rule is not the same for every metric.** See
`samples/reports/metric_catalog.md`. Four rules are mandatory, not stylistic:

1. `wind.wind_direction` is **circular**. Use a vector mean
   (`atan2(mean sin, mean cos)`), never a linear one. Measured: 17 north-crossings
   in a single 24 h capture, each producing a **180° error** under linear
   averaging — a north wind averages to south.
2. `wind.wind_gust` is an **extremum** over the interval. Aggregate with `max`;
   a mean systematically understates peak wind.
3. `rainfall_piezo.*` except `rain_rate` are **accumulators that reset**.
   Aggregate with `last`; a negative delta is a reset boundary, not negative rain.
4. Derived fields (`dew_point`, `feels_like`, `app_temp`, `vpd`, `app_tempin`)
   must be **recomputed from resampled inputs**, not resampled independently, or
   the stored record contradicts itself.

`soil_chN.ad` and the unitless `battery.*` status codes are excluded from
resampling entirely — carry the last value, never do arithmetic on them.

**Reconcile** — re-query a past window and compare against what is stored.
Discrepancies write to `change_log` with reason. Cadence TBD.

## 10. Non-negotiables

- **Never discard raw payloads.** Store the original response verbatim alongside
  any parsed form. Parsing bugs are recoverable; discarded data is not.
- **Store UTC.** The console has its own timezone setting; assume it disagrees.
- **Record the unit each value arrived in.** Console units are user-configurable
  (°F/°C, in/mm, inHg/hPa/mmHg) and can be changed after the fact.
- **Idempotent loads.** Backfill and incremental runs will overlap.
- **Rejected rows are quarantined, not dropped.** Out-of-range, malformed,
  duplicate-timestamp, and clock-drift rows go to a quarantine table with reason.
- **Fail loudly.** A silently dead scheduled job is the primary risk to this
  project.
- **Secrets never enter the repo.** Application Key, API Key, and DB/service
  credentials come from environment or a secret manager. Do not write them into
  config files, defaults, or test fixtures.
- **Tests use recorded fixtures, never the live API.**

## 11. Open decisions — ASK, do not assume

- [x] **Database target** — decided 2026-08-02: **Cloud SQL for PostgreSQL**.
      ~4.4M rows/yr is small; the workload is upsert- and change-detection-heavy,
      which is where BigQuery is weakest (costly quota-limited MERGE, streaming
      buffer complicating read-after-write). BigQuery remains sensible as a
      Phase 4 export target, not as the curated store.
- [x] **Where the job runs** — decided 2026-08-02: **Cloud Run job + Cloud
      Scheduler**. Chosen for §10's "a silently dead scheduled job is the
      primary risk": a sleeping workstation is exactly that failure mode, and a
      missing `run_log` row is only a signal if the runner was supposed to be up.
- [ ] **Schedule and cadence** — for incremental pulls and for reconciliation
- [ ] **Table shape** — ⏳ awaiting your call from real DDL. Both schemas are
      drafted and parse-checked: `schema/option_a_long.sql`,
      `schema/option_b_wide.sql`, compared in `schema/COMPARISON.md`.
      Recommendation is Option A (long store, wide view).
- [x] **Units to pin** — decided 2026-08-02: **imperial is canonical, metric is a
      derived view**. Pin `temp_unitid=2` (`ºF`), `pressure_unitid=4` (`inHg`),
      `wind_speed_unitid=9` (`mph`), `rainfall_unitid=13` (`in`, `in/hr`),
      `solar_irradiance_unitid=16` (`W/m²`). Stored rows then match the console
      display exactly.

      **Do not dual-ingest.** The API rounds each unit system independently to
      one decimal, so the two never agree: at one instant `outdoor.dew_point`
      returned `18.1 ℃` and `64.5 ºF`, but 18.1 ℃ is 64.58 ºF. Storing both as
      returned would bake in a permanent 0.02–0.08 ºF disagreement that
      reconciliation (§9) could not distinguish from real drift. Metric is
      computed on read from the canonical imperial value.
- [x] **`soil_chN.ad`** — decided 2026-08-02: **keep**, as an opaque integer.
      Not resampled, not interpolated, not unit-converted. Its relationship to
      `soilmoisture` is inferred, not observed; if it is ever established,
      derive it in a view rather than encoding the guess at ingest.
- [ ] **Resample interval and gap-fill rules** (§9) — note that `soil_chN.ad`
      and the unitless `battery.*` status codes are excluded from resampling
- [ ] **Retention policy for the local store** — presumed "keep everything," confirm
- [ ] **Flooding data source** (Phase 3) — sensor, format, cadence all unknown
- [x] **Python packaging/tooling** — decided 2026-08-01: stdlib `venv` + `pip`
      (not `uv`), `ruff` for lint/format, `pytest` for tests.

## 12. Reference documentation

- Ecowitt Cloud API v3 — `https://doc.ecowitt.net/web/#/apiv3en?page_id=1`
- HP2560 User Manual (17 Nov 2025) —
  `https://oss.ecowitt.net/uploads/20251121/HP2560UserManual.pdf`
  - §2.7.3 WiFi (2.4 GHz only) · §5.3 ecowitt.net registration ·
    §5.5 customized server · §4.1.14 interval · §4.4.6 SD backup
- WS View Plus & Web UI Manual —
  `https://oss.ecowitt.net/uploads/20250408/WS View Plus & Web UI Manual (Generic).pdf`
- Postman collection — `postman.com/barcar/ecowitt-cloud-api`
- Python reference impl — `github.com/pgarmyn/ecowitt_net` — **mechanics only,
  see §5.3 for what not to copy**
- Community wiki — `meshka.eu/Ecowitt/dokuwiki`

## 13. Commands

```bash
# install:        python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
# test:           pytest
# lint:           ruff check . && ruff format --check .

# credential check:  python -m discovery check
# recover MAC:       python -m discovery devices

# discovery run:  TBD — probe (D2), sample/inventory (D3), units (D4) not yet built
# incremental run: TBD — Phase 1
# backfill run:    TBD — Phase 1
# reconcile run:   TBD — Phase 1
```
