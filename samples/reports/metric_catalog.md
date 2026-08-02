# Metric catalog — semantics and resampling eligibility

Written 2026-08-02. Resolves the open items in D5 §5 by proposal.

This is **not** a schema. It is the data dictionary that a schema and the §9
resampler both depend on, and it is independent of the database target and of
the long-vs-wide decision — so it is safe to settle now.

The point of it: `CLAUDE.md` §9 requires resampling onto a fixed grid, and
**the correct resampling rule is not the same for every metric.** Applying one
rule uniformly is the kind of error that produces plausible numbers and is
invisible in model metrics until production (§8).

---

## Metric kinds

| kind | meaning | resample rule | count |
|---|---|---|---|
| `instantaneous` | a point-in-time reading | mean over the slot | 14 |
| `derived` | computed by Ecowitt from other fields | **recompute, never resample** | 5 |
| `circular` | an angle in degrees | **vector mean, never linear** | 1 |
| `extremum` | a max over the reporting interval | **max, never mean** | 1 |
| `accumulator` | a running total that resets | **last, then difference within a reset epoch** | 6 |
| `opaque` | meaning not established | **carry through, never interpolate** | 2 |
| `diagnostic` | hardware health, not weather | last | 4 |
| `status` | unitless code, not a measurement | **last, never arithmetic** | 3 |

---

## The four traps, with evidence

### 1. `wind.wind_direction` is circular — linear averaging is catastrophically wrong

Measured in the 24 h capture: **17 steps cross north**, and every one produces a
180° error under a linear mean.

| consecutive readings | linear mean | vector mean | error |
|---|---|---|---|
| 358º, 2º | 180.0º | **0.0º** | 180º |
| 345º, 1º | 173.0º | **353.0º** | 180º |
| 356º, 6º | 181.0º | **1.0º** | 180º |

A north wind averages to *south*. This station's wind sat near north for much of
the night, so this is the common case here, not an edge case.

**Rule:** resample with a vector mean —
`atan2(mean(sin θ), mean(cos θ)) mod 360`. Never linear-interpolate, never
linearly average, and never store a gap-filled direction without flagging it.

### 2. `wind.wind_gust` is an extremum, not a reading

Observed max gust 14.1 mph against max sustained speed 6.6 mph. A gust is the
**maximum over the reporting interval**. Averaging gusts across slots
systematically understates peak wind — which, for a flooding model, is
suppressing exactly the signal of interest.

**Rule:** aggregate with `max`, never `mean`.

### 3. Five fields are derived, not measured

`outdoor.feels_like`, `outdoor.app_temp`, `outdoor.dew_point`, `outdoor.vpd`,
`indoor.dew_point`, `indoor.feels_like`, `indoor.app_tempin` are all computed by
Ecowitt from temperature and humidity.

Resample them independently and they will no longer agree with the temperature
and humidity stored beside them — the record becomes internally inconsistent, and
a model trained on it can learn the inconsistency.

**Rule:** either recompute from resampled inputs, or carry them but mark them
derived so no feature pipeline treats them as independent observations. Storing
them is still worthwhile: they are the vendor's own values, useful for
cross-checking any reimplementation.

### 4. Accumulators reset, so differencing across a reset goes negative

`rainfall_piezo.daily` / `weekly` / `monthly` / `yearly` / `event` / `1_hour` are
running totals on independent reset schedules. Only `rain_rate` is
instantaneous.

Rainfall was flat at zero across the whole capture, so **no reset was observed** —
this trap is inferred from the field semantics, not measured. It will not
manifest until the first rain.

**Rule:** aggregate with `last`. To derive per-slot rainfall, difference within a
reset epoch and treat any negative delta as a reset boundary, not as negative
rain.

---

## Full catalog

| metric | kind | unit | resample | notes |
|---|---|---|---|---|
| `outdoor.temperature` | instantaneous | `ºF` | mean | |
| `outdoor.humidity` | instantaneous | `%` | mean | |
| `outdoor.feels_like` | derived | `ºF` | recompute | from temp + humidity |
| `outdoor.app_temp` | derived | `ºF` | recompute | |
| `outdoor.dew_point` | derived | `ºF` | recompute | |
| `outdoor.vpd` | derived | `inHg` | recompute | vapour pressure deficit |
| `indoor.temperature` | instantaneous | `ºF` | mean | |
| `indoor.humidity` | instantaneous | `%` | mean | |
| `indoor.dew_point` | derived | `ºF` | recompute | |
| `indoor.feels_like` | derived | `ºF` | recompute | |
| `indoor.app_tempin` | derived | `ºF` | recompute | |
| `pressure.absolute` | instantaneous | `inHg` | mean | station pressure |
| `pressure.relative` | instantaneous | `inHg` | mean | ⚠️ identical to absolute — see below |
| `wind.wind_speed` | instantaneous | `mph` | mean | already an interval average |
| `wind.wind_gust` | **extremum** | `mph` | **max** | trap 2 |
| `wind.wind_direction` | **circular** | `º` | **vector mean** | trap 1 |
| `solar_and_uvi.solar` | instantaneous | `W/m²` | mean | |
| `solar_and_uvi.uvi` | instantaneous | `` | mean | integer index |
| `rainfall_piezo.rain_rate` | instantaneous | `in/hr` | mean | only instantaneous rain metric |
| `rainfall_piezo.event` | accumulator | `in` | last | trap 4 |
| `rainfall_piezo.1_hour` | accumulator | `in` | last | docs call this `hourly` |
| `rainfall_piezo.daily` | accumulator | `in` | last | |
| `rainfall_piezo.weekly` | accumulator | `in` | last | |
| `rainfall_piezo.monthly` | accumulator | `in` | last | |
| `rainfall_piezo.yearly` | accumulator | `in` | last | |
| `temp_and_humidity_ch1..3.temperature` | instantaneous | `ºF` | mean | 3 channels |
| `temp_and_humidity_ch1..3.humidity` | instantaneous | `%` | mean | 3 channels |
| `soil_ch1..2.soilmoisture` | instantaneous | `%` | mean | 2 channels |
| `soil_ch1..2.ad` | **opaque** | `` | **carry** | decided 2026-08-02: keep, never interpolate |
| `battery.haptic_array_battery` | diagnostic | `V` | last | |
| `battery.haptic_array_capacitor` | diagnostic | `V` | last | |
| `battery.soilmoisture_sensor_ch1..2` | diagnostic | `V` | last | |
| `battery.temp_humidity_sensor_ch1..3` | **status** | `` | **last** | real-time only; no arithmetic |

## Open, still needs your call

- **`pressure.relative` == `pressure.absolute`** in every capture (`29.24`–
  `29.26`). Relative pressure is normally sea-level-adjusted; identical values
  mean the console's altitude offset is unset. At 35.25 N, −95.53 W the station
  is roughly 180 m above sea level, so relative should read meaningfully higher.
  **This is a console setting, not a pipeline bug** — but if it stays unset,
  storing both fields is storing the same number twice, and any model feature
  built on "relative pressure" is really station pressure.
- **Whether to store derived fields at all.** Recommendation: yes, marked as
  derived. They cost little and are the vendor's own reference values.
