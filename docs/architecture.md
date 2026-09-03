# Architecture

How data gets from the console to a query. Rendered version with commentary:
<https://claude.ai/code/artifact/63da25f0-c8a0-43e8-a0b6-a4fcc17400d5>

These diagrams render natively in GitHub and in VS Code's markdown preview.


## End to end

The console has no local API — it pushes to Ecowitt's cloud and nothing else, so the
pipeline pulls rather than listening on the LAN. Nothing accepts inbound connections:
Postgres binds to localhost, and SSH reaches the box only through an IAP tunnel.

```mermaid
flowchart TB
  subgraph HOUSE["At the house"]
    HP["HP2560 console<br/>42 metrics · outbound push only"]
  end
  subgraph NET["ecowitt.net"]
    API["Cloud API v3<br/>5-min grid · rolling 3-month window"]
  end
  subgraph GCP["GCP · ecowitt-504320 · us-central1-a"]
    subgraph VM["e2-micro · ecowitt-db"]
      TIMERS["systemd timers<br/>ingest · reconcile · backup · heartbeat"]
      JOB["python -m ingest"]
      PG[("PostgreSQL 16<br/>listens on localhost only")]
    end
    SM["Secret Manager<br/>API keys"]
    GCS["Cloud Storage<br/>verified nightly dumps"]
    CL["Cloud Logging<br/>2 alert policies"]
  end
  subgraph MAC["Your Mac"]
    TUN["SSH tunnel via IAP<br/>localhost:5433"]
    TOOLS["pgAdmin · notebook<br/>read-only role"]
  end

  HP -->|"WiFi, every ~1 min"| API
  TIMERS --> JOB
  SM -.->|"fetched at runtime,<br/>never on disk"| JOB
  API -->|"GET /device/history"| JOB
  JOB --> PG
  PG -->|"pg_dump, verified<br/>both ends"| GCS
  PG -.->|"staleness + liveness"| CL
  TUN -->|"reads"| PG
  TOOLS --> TUN
```

## Inside one hourly run

The order is deliberate. Raw lands **before** validation, so a response that fails a
check can still be inspected. Resolution is verified **before** normalisation, so coarse
data never enters the curated table wearing a fine-grained label.

A run that changes nothing still writes a `run_log` row — absence of a row means the job
did not run, which is a different failure from a run that found nothing new.

```mermaid
flowchart TB
  A["open run_log · status = running"] --> B["build request<br/>units pinned · dates in console-local time"]
  B --> C["GET /device/history<br/>4-hour window · cycle_type=5min"]
  C --> D["LAND RAW VERBATIM<br/>raw_payload · append-only"]
  D --> E{"measured spacing<br/>= 300s?"}
  E -->|"no"| F["ResolutionError<br/>run fails · nothing stored"]
  E -->|"yes"| G["normalize to long rows"]
  G --> H{"parses? timestamp plausible?<br/>unit matches catalog?"}
  H -->|"no"| I["quarantine, with a reason"]
  H -->|"yes"| J["compare against what is stored"]
  J --> K{"different?"}
  K -->|"absent"| L["INSERT"]
  K -->|"changed"| M["UPDATE + write change_log"]
  K -->|"identical"| N["count as unchanged<br/>no write at all"]
  L --> Z["close run_log · counts recorded"]
  M --> Z
  N --> Z
  I --> Z

  classDef guard fill:#E2F0EC,stroke:#226256,color:#123A33
  classDef risk  fill:#F7E4DE,stroke:#9A4128,color:#5E2716
  classDef land  fill:#F6EEDF,stroke:#97671F,color:#4A3210
  class E,H,K guard
  class F,I risk
  class D land
```

## Who calls what — every moving part, by file

Lanes are responsibilities; boxes are the actual files. Read top to bottom: a timer
fires, a shell script resolves secrets, the CLI decides the window, the client makes
the HTTP call, normalisation turns the body into rows, and `db.py` is the only module
that writes SQL.

Two rules the layout is enforcing. **Nothing except `db.py` touches Postgres** — so
"was this written?" is answerable by reading one file. And **`client.py` is shared
between discovery and ingestion** — Phase 0's capture guarantees (redact credentials,
land raw before parsing) apply to production pulls because it is literally the same
code path, not a reimplementation of it.

Solid arrows are calls; dotted arrows are data or definitions moving without one.
Returns are left out to keep the flow one-directional — the next diagram down has them,
in order.

```mermaid
flowchart TB
  subgraph L1["① Triggers · infra/"]
    direction LR
    T1["ecowitt-ingest.timer<br/>hourly"] --> RS["run_ingest.sh<br/>secrets to env<br/>exec venv python"]
    T2["ecowitt-reconcile.timer<br/>10:00 UTC"] --> RS
    T3["ecowitt-gaps.timer<br/>Sun 11:00 UTC"] --> RS
    T4["ecowitt-backup.timer<br/>09:00 UTC"] --> BK["backup.sh"]
    T5["ecowitt-heartbeat.timer<br/>every 15 min"] --> HB["heartbeat.sh"]
  end

  subgraph L2["② CLI and orchestration · src/ingest/"]
    direction LR
    MAIN["__main__.py<br/>cmd_incremental · cmd_reconcile<br/>cmd_backfill · cmd_gaps"] -->|"reads constants"| CFG["config.py<br/>UNIT_PARAMS · HISTORY_GROUPS<br/>CHUNK 12h · CYCLE_TYPE 5min"]
    MAIN -->|"chunks the window"| PIPE["pipeline.py<br/>chunks · fetch_and_load<br/>verify_resolution · verify_groups"]
  end

  subgraph L3["③ HTTP · src/discovery/"]
    direction LR
    PROBE["probe.py<br/>resolve_console_tz"] -->|"device_info"| CLI2["client.py<br/>EcowittClient.history<br/>.real_time · .device_info"]
  end

  subgraph L4["④ Transform · src/ingest/"]
    NORM["normalize.py<br/>normalize_history · median_delta<br/>duplicate_keys"]
  end

  subgraph L5["⑤ Persistence · src/ingest/"]
    direction LR
    DBM["db.py<br/>run_logged · land_raw · load_observations<br/>quarantine · missing_slots"]
    DDL["schema/*.sql<br/>tables · CHECKs · triggers · views"]
  end

  subgraph L6["⑥ Outside the process"]
    direction LR
    SM["Secret Manager"]
    API["api.ecowitt.net/api/v3"]
    RAW["/opt/ecowitt/raw/*.json<br/>verbatim capture"]
    PG[("PostgreSQL 16<br/>localhost only")]
    GCS["Cloud Storage"]
    LOG["Cloud Logging"]
  end

  RS -->|"python -m ingest MODE"| MAIN
  RS -.->|"gcloud secrets access"| SM
  MAIN -->|"resolve_console_tz"| PROBE
  PIPE -->|"client.history"| CLI2
  CLI2 -->|"GET device/history"| API
  CLI2 -->|"writes before parsing"| RAW
  CLI2 -.->|"payload"| NORM
  PIPE -->|"normalize_history(payload)"| NORM
  NORM -->|"observations · rejections<br/>measured spacing"| DBM
  MAIN -->|"connect · run_logged"| DBM
  PIPE -->|"land_raw · load_observations · quarantine"| DBM
  DBM -->|"the only SQL writer"| PG
  DDL -.->|"defines"| PG
  BK -->|"pg_dump · verify · row count"| PG
  BK -->|"upload, then re-read"| GCS
  HB -->|"5 staleness queries"| PG
  HB -->|"logs every run, healthy or not"| LOG

  classDef ext fill:#E8EEF4,stroke:#3D6383,color:#1D3348
  class SM,API,RAW,PG,GCS,LOG ext
```

## One hourly run, call by call

The same run as "Inside one hourly run" above, but attributed to files. Every arrow is
a real function call; the notes are the guards that live at that boundary.

```mermaid
sequenceDiagram
  autonumber
  participant TMR as ecowitt-ingest.timer
  participant SH as run_ingest.sh
  participant CLI as ingest/__main__.py
  participant PIPE as ingest/pipeline.py
  participant EC as discovery/client.py
  participant NZ as ingest/normalize.py
  participant DB as ingest/db.py
  participant PG as PostgreSQL

  TMR->>SH: ExecStart run_ingest.sh incremental
  SH->>SH: gcloud secrets access -> env
  SH->>CLI: python -m ingest incremental
  CLI->>EC: device_info()
  EC-->>CLI: date_zone_id = America/Chicago
  Note over CLI,EC: IANA zone, not an offset — backfill<br/>windows cross DST transitions
  CLI->>DB: run_logged(trigger, mode, window)
  DB->>PG: INSERT run_log status=running
  CLI->>PIPE: fetch_and_load(start_utc, end_utc)
  PIPE->>EC: history(start/end in console-local, 5min, units pinned)
  EC->>EC: write raw .json before parsing
  EC-->>PIPE: RawResponse
  PIPE->>DB: land_raw(body_bytes)
  DB->>PG: INSERT raw_payload (append-only)
  Note over PIPE: raise_if_failed() runs AFTER landing —<br/>a failed body is still on disk
  PIPE->>NZ: normalize_history(payload)
  NZ-->>PIPE: observations · rejections · median spacing
  PIPE->>PIPE: verify_resolution(300s ± 60s)
  Note over PIPE: 30-min data returns code=0 too —<br/>ResolutionError stops the run here
  PIPE->>DB: load_observations(rows)
  DB->>PG: staging -> change_log -> INSERT ... ON CONFLICT
  Note over DB,PG: WHERE clause on DO UPDATE:<br/>identical rows are counted, never written
  PIPE->>DB: quarantine(rejections)
  DB->>PG: INSERT quarantine, with a reason
  CLI->>DB: close run_logged
  DB->>PG: UPDATE run_log status + counts
```

## The same thing as a table

| File | Triggered by | Calls out to | Produces |
|---|---|---|---|
| [infra/ecowitt-*.timer](../infra/) | systemd | matching `.service` | The only schedule; nothing else is time-aware |
| [infra/run_ingest.sh](../infra/run_ingest.sh#L19) | ingest · reconcile · gaps services | Secret Manager, `python -m ingest` | Credentials in env, never on disk |
| [src/ingest/__main__.py](../src/ingest/__main__.py#L102-L158) | CLI | `config`, `probe`, `db`, `pipeline` | Window list per mode; exit codes 0/1/2 |
| [src/ingest/config.py](../src/ingest/config.py#L20-L68) | imported | — | Pinned unit IDs, 12 groups, 12 h chunk, 5 min grid |
| [src/ingest/pipeline.py](../src/ingest/pipeline.py#L80-L150) | `__main__` | `client`, `normalize`, `db` | One chunk end to end; `ResolutionError` |
| [src/discovery/client.py](../src/discovery/client.py#L252-L283) | pipeline, probe, discovery CLI | Ecowitt API, raw dir | `RawResponse` + verbatim `.json`/`.meta.json` |
| [src/discovery/probe.py](../src/discovery/probe.py#L101) | `__main__` | `client.device_info` | Console IANA timezone, with fallback |
| [src/ingest/normalize.py](../src/ingest/normalize.py#L90-L207) | pipeline | — | Long rows, rejections, measured spacing |
| [src/ingest/db.py](../src/ingest/db.py#L46-L322) | `__main__`, pipeline | PostgreSQL | Every INSERT/UPDATE in the project |
| [schema/](../schema/) | applied once | — | Tables, CHECKs, append-only trigger, views |
| [infra/heartbeat.sh](../infra/heartbeat.sh#L38-L48) | heartbeat.timer | Postgres, Cloud Logging | 5 staleness queries → one log line, always |
| [infra/backup.sh](../infra/backup.sh#L38-L85) | backup.timer | `pg_dump`, GCS, Postgres | Verified dump + a `backup_log` row |
| [infra/tunnel.sh](../infra/tunnel.sh) | you, manually | IAP, Postgres | localhost:5433 for pgAdmin and the notebook |
| [src/discovery/__main__.py](../src/discovery/__main__.py#L219) | you, manually | `client`, `probe`, `units`, `inventory` | `samples/reports/*.md` — Phase 0, not scheduled |

⚠️ `ecowitt-gaps.timer` is the one unit no deploy script installs — [deploy_ingest.sh](../infra/deploy_ingest.sh#L38)
enables ingest and reconcile only, so the gap sweep was enabled by hand and a rebuild
of the VM would silently come back without it.

## Where it lands

One row per (station, timestamp, metric). Long rather than wide because `change_log` is
field-level, so the table's key and the audit key are the same tuple — and adding a
sensor is two inserts rather than a migration.

```mermaid
erDiagram
  run_log        ||--o{ raw_payload    : "lands"
  run_log        ||--o{ observation    : "first / last seen"
  run_log        ||--o{ change_log     : "attributes"
  run_log        ||--o{ quarantine     : "rejects into"
  metric_catalog ||--o{ observation    : "metric + unit, composite FK"
  metric_catalog ||--o{ change_log     : "metric"
  observation    ||--o{ observation_wide : "pivoted into"

  observation {
    text   station_id  PK
    tstz   ts_utc      PK
    text   metric      PK
    text   value_text  "exact bytes as returned"
    float  value_num   "null if it will not parse"
    text   unit        "exact bytes, never normalised"
    enum   source      "observed | resampled | backfilled"
  }
  metric_catalog {
    text   metric         PK
    enum   kind           "circular, extremum, accumulator..."
    text   canonical_unit "pinned per request"
    text   resample_rule  "vector_mean, max, last, mean"
    bool   resamplable
  }
  raw_payload {
    bigint raw_id      PK
    jsonb  body        "verbatim, append-only"
    bytea  body_sha256
    text   request_url "credentials redacted, CHECK-enforced"
  }
```

## Getting it back out

Postgres never leaves localhost. The read-only role is refused writes twice over: by
grant, and by a forced read-only transaction default.

```mermaid
flowchart LR
  T["./infra/tunnel.sh"] -->|"IAP · port 5433"| PG[("PostgreSQL")]
  PG --> W["observation_wide<br/>one row per timestamp"]
  PG --> M["observation_wide_metric<br/>°C · hPa · m/s"]
  PG --> L["observation<br/>canonical long table"]
  W --> NB["notebooks/explore.ipynb<br/>hour × metric table"]
  M --> NB
  L --> PGA["pgAdmin"]
  W --> PGA

  classDef ro fill:#E2F0EC,stroke:#226256,color:#123A33
  class T ro
```

## The guards, and what each is for

| Guard | Prevents | Measured evidence |
|---|---|---|
| Spacing verification | Asking for 5-min data and silently getting 30-min, with a success code | Honored to 24 h; 48 h → 30 min, 30 d → 4 hour, all `code=0` |
| Console-local date framing | An empty result that looks like "no data" | UTC framing returns `code=0` and an empty body |
| 12-hour chunks | A 24 h window becoming 25 wall-clock hours on spring-forward | Not yet observed — arrives once a year |
| Composite FK `(metric, unit)` | A unit changing underneath stored history | `℃` rejected for a `ºF`-pinned metric |
| Exact unit bytes | Normalising `º` (U+00BA) to `°` (U+00B0) | Stored and read back as U+00BA |
| Change detection | A blind upsert making "unchanged" invisible | Re-run of one window: 0 ins, 0 upd, 1,794 unchanged |
| Append-only raw | Losing the original response to a parsing bug | Trigger raises on UPDATE/DELETE; verified |
| Quarantine | Dropping a malformed row unnoticed | 0 so far; every reject carries a reason |
| Per-metric resample rules | Averaging a wind direction into its opposite | 17 north-crossings in a day; 29.9° measured error |
| Heartbeat absence alarm | A dead machine looking like a quiet healthy one | Emits every 15 min; the alert fires on silence |

**The pattern behind all of them:** this API prefers returning nothing over returning an
error. A wrong unit ID, a mis-framed window, an over-wide span, a misspelled sensor group
— each comes back as `code=0` with a plausible body. Almost every guard converts one of
those silences into a loud failure.

## What runs unattended

| Timer | When | Does |
|---|---|---|
| `ecowitt-ingest` | hourly | Last 4 h; each 5-min point fetched ~4× |
| `ecowitt-reconcile` | 10:00 UTC | Previous 24 h in 2 × 12 h chunks |
| `ecowitt-backup` | 09:00 UTC | Dump → verify → upload → re-read size |
| `ecowitt-heartbeat` | every 15 min | Staleness check; logs every run, healthy or not |

Reconciliation runs an hour *after* the backup so a pass that rewrites values is captured
by the next night's dump rather than racing the current one.
