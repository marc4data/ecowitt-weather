# D2 — Granularity probe results

Generated 2026-08-02T04:50:09.289550+00:00 · `call_back=outdoor.temperature`

Console UTC offset detected at runtime: **-5.00 h**. All request
windows below were framed in console-local time; all timestamps shown are UTC.

## Span sweep

| cycle_type | span | HTTP | code | points | median Δ | min Δ | max Δ | honored? | bytes | secs |
|---|---|---|---|---|---|---|---|---|---|---|
| `5min` | 1h | 200 | 0 | 13 | 300s | 300 | 300 | yes | 365 | 1.1 |
| `auto` | 1h | 200 | 0 | 13 | 300s | 300 | 300 | auto -> 5min | 365 | 1.0 |
| `5min` | 6h | 200 | 0 | 73 | 300s | 300 | 300 | yes | 1,565 | 1.0 |
| `auto` | 6h | 200 | 0 | 73 | 300s | 300 | 300 | auto -> 5min | 1,565 | 1.1 |
| `5min` | 24h | 200 | 0 | 289 | 300s | 300 | 300 | yes | 5,885 | 1.7 |
| `auto` | 24h | 200 | 0 | 289 | 300s | 300 | 300 | auto -> 5min | 5,885 | 1.0 |
| `5min` | 48h | 200 | 0 | 49 | 1800s | 1800 | 1800 | NO -> 30min | 1,085 | 1.1 |
| `auto` | 48h | 200 | 0 | 49 | 1800s | 1800 | 1800 | auto -> 30min | 1,085 | 1.1 |
| `5min` | 7d | 200 | 0 | 49 | 1800s | 1800 | 1800 | NO -> 30min | 1,085 | 0.9 |
| `auto` | 7d | 200 | 0 | 49 | 1800s | 1800 | 1800 | auto -> 30min | 1,085 | 1.0 |
| `5min` | 30d | 200 | 0 | 6 | 14400s | 14400 | 14400 | NO -> 4hour | 225 | 1.0 |
| `auto` | 30d | 200 | 0 | 6 | 14400s | 14400 | 14400 | auto -> 4hour | 225 | 1.0 |
| `5min` | 90d | 200 | 0 | 0 | — | — | — | n/a | 56 | 1.2 |
| `auto` | 90d | 200 | 0 | 0 | — | — | — | n/a | 56 | 0.9 |

## Retention probes (24 h windows, `cycle_type=5min`)

| age | HTTP | code | points | median Δ | honored? | window (UTC) |
|---|---|---|---|---|---|---|
| 30d ago | 200 | 0 | 0 | — | VOID — predates station history | 2026-07-02 04:00 → 04:00 |
| 100d ago | 200 | 0 | 0 | — | VOID — predates station history | 2026-04-23 04:00 → 04:00 |
| 400d ago | 200 | 0 | 0 | — | VOID — predates station history | 2025-06-27 04:00 → 04:00 |

> **Oldest observation returned by any probe: 2026-08-01T00:00:00+00:00.**
> Windows ending before that are marked VOID: they measure the station's age,
> not the API's retention policy. The retention tiers in CLAUDE.md §6 remain
> UNVERIFIED and must be re-probed once the station has months of history.

## Conclusions

- **Maximum span for which `cycle_type=5min` is honored: 24h.**
  That is the backfill chunk size for Phase 1.
- **Silent downgrade observed: YES.**
  The API returned `code=0` with coarser spacing than requested. Phase 1 must verify returned timestamp spacing on every response and reject or re-chunk on mismatch — the request parameters cannot be trusted.
