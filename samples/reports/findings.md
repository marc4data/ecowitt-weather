# D5 — Phase 0 findings and recommendation

Written 2026-08-02, after D1–D4. Everything below is grounded in captures under
`samples/raw/`; where something is inferred rather than observed, it says so.

---

## 1. Did the `CLAUDE.md` §5.1–5.2 hypotheses hold?

**Response shapes: yes, exactly.** All 42 real-time leaves carry `{time, unit,
value}`; all 39 history leaves carry `{unit, list}`. Every value arrives as a
string, and — on this station — every one parses as a float.

**Request mechanics: no, in three ways that would each have corrupted data
silently.**

| Hypothesis | Reality |
|---|---|
| `call_back=all` works on both endpoints | History rejects it, `code=40016`. Real-time only. |
| `start_date`/`end_date` are UTC | They are **console-local**. UTC framing returns `code=0` with an empty body. |
| Unit IDs must be read from the docs | The API states its own valid ranges in its error messages. |

None of these fail loudly. All three produce `code=0` with plausible-looking
output. That is the single most important characteristic of this API: **it
prefers returning nothing over returning an error.**

Two further corrections to the published documentation, both confirmed against
live captures:

- The docs call the field `rainfall_piezo.hourly`. The wire name is
  **`rainfall_piezo.1_hour`**.
- This station returns four fields the docs do not list at all: `outdoor.vpd`,
  `indoor.dew_point`, `indoor.feels_like`, `indoor.app_tempin`.

The documentation cannot be used as a schema source. Only captures can.

## 2. Maximum reliable `5min` span

**24 hours.** That is the Phase 1 backfill chunk size.

## 3. Does silent downgrade occur, and how is it detected?

**Yes.** Requesting `cycle_type=5min` over 48 h returns 30-minute data; over
30 d it returns 4-hour data. Both with `code=0` and no warning. A 90 d span
returns zero points, also with `code=0`.

Detection has to be structural, because nothing in the response declares its
own resolution:

> **Measure the median delta between returned timestamps on every response and
> compare it against the `cycle_type` requested. Reject or re-chunk on
> mismatch.** Never infer resolution from the request parameters.

`probe.EXPECTED_DELTA_S` already encodes the nominal spacing per `cycle_type`;
Phase 1 should reuse it rather than restate it.

## 4. Recommendation on table shape

**Long/tall as the curated store, wide as a derived view.**

```
curated_observation:  station_id · ts_utc · metric · value · unit · run_id
                      PK (station_id, ts_utc, metric)
wide_observation:     a VIEW pivoting the above, for modelling and eyeballing
```

This mirrors the unit decision already taken — one canonical truth, convenient
shapes derived on read.

**Why long wins, despite wide being the easier thing to query:**

1. **New sensors must not require a migration.** The HP2560 supports up to 8
   temperature/humidity channels and 16 soil channels. Two soil and three T/RH
   are attached today. Every sensor added later is a new row in long and a
   schema change in wide — and schema changes to a table holding training data
   are exactly what Phase 4 cannot tolerate.
2. **Some group names are not knowable in advance.** The published example
   shows groups keyed as `WFC01-0xxxxxx8(WFC01 Default Title)` — a device
   identifier and a *user-editable title* concatenated into the key. A wide
   table cannot have a column per unknowable name; renaming the device on the
   console would rename the column.
3. **`change_log` (§7) is already field-level.** Its natural key is
   `(station, ts_utc, metric)` — which is precisely the long table's primary
   key. Change detection becomes a row comparison instead of a column-by-column
   diff across ~40 columns.
4. **Point-in-time reconstruction (§8) is a filter, not a pivot.** "What did
   timestamp T look like as of date D" is a `WHERE` clause over long rows.
5. **Units belong to the metric, not the row.** `outdoor.vpd` is `inHg` while
   `outdoor.temperature` is `ºF`. Long carries the unit per observation
   naturally, which §10 requires; wide would need 40 parallel unit columns or a
   side table.

**The strongest argument against long is weaker than it looks.** Wide is
usually favoured when metrics share a timestamp grid — and here they genuinely
do: all 39 history metrics returned an **identical 281-timestamp set**, with no
ragged edges. That makes the pivot to wide clean and cheap. But it is an
argument for the *view* being easy, not for the *store* being wide.

Row volume is not a concern: 42 metrics × 288 slots/day ≈ 12k rows/day, about
4.4M rows/year. That is small for any of the three candidate databases.

## 5. Fields needing a decision before schema design

- ✅ **`soil_chN.ad` — DECIDED 2026-08-02: keep.** An unlabelled integer
  (unit `""`) shipped alongside `soilmoisture`. Observed 149–151 on ch1,
  129–131 on ch2, moving inversely to moisture. Very likely the raw ADC reading
  behind the percentage, but that is inference, not observation — so it is
  stored as an **opaque integer**, never resampled or interpolated, and never
  unit-converted. If the ADC↔percentage relationship is later established it
  can be derived in a view; deriving it now would encode a guess as data.
  Retaining it is cheap insurance: if `soilmoisture` turns out to be a lossy or
  recalibrated projection of `ad`, the raw signal is the recoverable one, which
  is the §10 argument for never discarding raw.
- **`battery.*` is not one kind of thing.** `haptic_array_battery` and
  `soilmoisture_sensor_chN` are volts; `temp_humidity_sensor_chN` are unitless
  status codes that only ever read `0`. **Status codes must not be resampled or
  interpolated** — a mean of two status codes is meaningless. They should
  either live outside the observation table or carry a flag excluding them from
  numeric treatment.
- **`rainfall_piezo` accumulators** (`daily`, `weekly`, `monthly`, `yearly`,
  `event`) are running totals that reset on their own schedules, not
  instantaneous readings. Resampling them with the same rules as temperature
  would be wrong. `rain_rate` is the only instantaneous rainfall metric.
- **`pressure.relative` and `pressure.absolute` were identical** in all
  captures (`29.24`–`29.26`). That implies the console's altitude offset is
  unset. Worth confirming on the console — if relative is meant to be
  sea-level-adjusted, it currently is not.

## 6. Anything surprising

**Gaps are normal, not exceptional.** The 24-hour history capture returned
**281 of an expected 289 points** — two dropouts totalling 8 missing 5-minute
slots (20 min and 30 min), on a healthy station less than two weeks old.

That is ~2.8% loss in a single ordinary day, and it reframes §9. Gap detection
cannot treat any hole as an incident or it will alarm constantly. It needs a
threshold, and the resampler needs an explicit rule for holes this size — with
synthesized values distinguishable from observed ones, as §9 already demands.

Both gaps fell near local midnight (23:15–23:35 and 00:10–00:40 America/
Chicago). **One day is not enough to call that a pattern**, but it is worth
watching: if dropouts cluster at a fixed local time, that is a console or
upload behaviour rather than random loss.

**Registration date is not first-data date.** `/device/info` reports
`createtime` of 2026-07-23, but no history exists before 2026-08-01. Nine days
unaccounted for. Phase 1 must not use `createtime` as a backfill floor.

**The API has undocumented endpoints that answer questions we were solving the
hard way.** `/device/info` returns `date_zone_id` (`America/Chicago`), the MAC,
lat/long, and an embedded copy of the entire real-time payload. Neither it nor
`/device/list` appears in §5.1. Conversely `device/setting`, `device/unit`,
`device/detail` and `user/info` all return `code=404` — **there is no endpoint
exposing the console's unit configuration**, which is why units are pinned per
request.

**The API is not self-consistent about character encoding.** `temp_unitid=1`
returns `℃` (U+2103) but `temp_unitid=2` returns `ºF` (U+00BA MASCULINE ORDINAL
INDICATOR + `F`) — two conventions from one parameter. The published example
additionally uses `℉` (U+2109) and mixes `µ` (U+00B5) with `μ` (U+03BC). Unit
strings must be compared and stored as exact bytes; a `°`/`º` normalisation
would silently rewrite history.

## 7. Still unanswered

- **Retention tiers (§6) remain UNVERIFIED.** The station has ~1 day of
  history, so every retention probe returned empty for lack of data rather than
  lack of retention. Re-probe once months have accumulated.
- **Unit IDs 17–23 are unaccounted for.** IDs are globally unique across
  parameters; the six known families skip that range, so unit parameters exist
  that this project has not named.
- **The exact `5min` cutoff between 24 h and 48 h was not bisected.** 24 h is
  used because it is both safe and a natural chunk.
- **Console push interval and SD interval** are still unconfirmed on the
  hardware.
