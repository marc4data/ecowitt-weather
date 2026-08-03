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
