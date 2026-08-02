# D3 — Field inventory

Generated 2026-08-02T06:27:29.418626+00:00 from captures on disk — no API calls.

Sources: 4 real-time capture(s), 1 history capture(s). 42 distinct field paths.

| field path | endpoints | raw type | examples | unit | null rate | float? |
|---|---|---|---|---|---|---|
| `data.battery.haptic_array_battery` | history, real_time | str | `3.28`, `3.26` | `V` | 0/285 | yes |
| `data.battery.haptic_array_capacitor` | history, real_time | str | `4.9`, `4.8`, `4.7` | `V` | 0/285 | yes |
| `data.battery.soilmoisture_sensor_ch1` | history, real_time | str | `1.6` | `V` | 0/285 | yes |
| `data.battery.soilmoisture_sensor_ch2` | history, real_time | str | `1.6` | `V` | 0/285 | yes |
| `data.battery.temp_humidity_sensor_ch1` | real_time | str | `0` | `` | 0/4 | yes |
| `data.battery.temp_humidity_sensor_ch2` | real_time | str | `0` | `` | 0/4 | yes |
| `data.battery.temp_humidity_sensor_ch3` | real_time | str | `0` | `` | 0/4 | yes |
| `data.indoor.app_tempin` | history, real_time | str | `75.4`, `76.2`, `76.9` | `ºF` | 0/285 | yes |
| `data.indoor.dew_point` | history, real_time | str | `53.5`, `54.0`, `54.6` | `ºF` | 0/285 | yes |
| `data.indoor.feels_like` | history, real_time | str | `74.3`, `75.0`, `75.5` | `ºF` | 0/285 | yes |
| `data.indoor.humidity` | history, real_time | str | `48`, `49`, `50` | `%` | 0/285 | yes |
| `data.indoor.temperature` | history, real_time | str | `74.3`, `75.0`, `75.5` | `ºF` | 0/285 | yes |
| `data.outdoor.app_temp` | history, real_time | str | `92.2`, `92.1`, `91.7` | `ºF` | 0/285 | yes |
| `data.outdoor.dew_point` | history, real_time | str | `71.2`, `70.8`, `70.3` | `ºF` | 0/285 | yes |
| `data.outdoor.feels_like` | history, real_time | str | `91.0`, `90.5`, `89.9` | `ºF` | 0/285 | yes |
| `data.outdoor.humidity` | history, real_time | str | `62`, `63`, `64` | `%` | 0/285 | yes |
| `data.outdoor.temperature` | history, real_time | str | `85.5`, `85.3`, `85.1` | `ºF` | 0/285 | yes |
| `data.outdoor.vpd` | history, real_time | str | `0.463`, `0.465`, `0.469` | `inHg` | 0/285 | yes |
| `data.pressure.absolute` | history, real_time | str | `29.24`, `29.25`, `29.26` | `inHg` | 0/285 | yes |
| `data.pressure.relative` | history, real_time | str | `29.24`, `29.25`, `29.26` | `inHg` | 0/285 | yes |
| `data.rainfall_piezo.1_hour` | history, real_time | str | `0.00` | `in` | 0/285 | yes |
| `data.rainfall_piezo.daily` | history, real_time | str | `0.00` | `in` | 0/285 | yes |
| `data.rainfall_piezo.event` | history, real_time | str | `0.00` | `in` | 0/285 | yes |
| `data.rainfall_piezo.monthly` | history, real_time | str | `0.00` | `in` | 0/285 | yes |
| `data.rainfall_piezo.rain_rate` | history, real_time | str | `0.00` | `in/hr` | 0/285 | yes |
| `data.rainfall_piezo.weekly` | history, real_time | str | `0.05`, `0.00` | `in` | 0/285 | yes |
| `data.rainfall_piezo.yearly` | history, real_time | str | `0.05` | `in` | 0/285 | yes |
| `data.soil_ch1.ad` | history, real_time | str | `151`, `150`, `149` | `` | 0/285 | yes |
| `data.soil_ch1.soilmoisture` | history, real_time | str | `23`, `22` | `%` | 0/285 | yes |
| `data.soil_ch2.ad` | history, real_time | str | `131`, `130`, `129` | `` | 0/285 | yes |
| `data.soil_ch2.soilmoisture` | history, real_time | str | `18` | `%` | 0/285 | yes |
| `data.solar_and_uvi.solar` | history, real_time | str | `0.0`, `0.1`, `0.2` | `W/m²` | 0/285 | yes |
| `data.solar_and_uvi.uvi` | history, real_time | str | `0`, `1`, `2` | `` | 0/285 | yes |
| `data.temp_and_humidity_ch1.humidity` | history, real_time | str | `51`, `50`, `52` | `%` | 0/285 | yes |
| `data.temp_and_humidity_ch1.temperature` | history, real_time | str | `78.0`, `77.9`, `78.1` | `ºF` | 0/285 | yes |
| `data.temp_and_humidity_ch2.humidity` | history, real_time | str | `46`, `47`, `48` | `%` | 0/285 | yes |
| `data.temp_and_humidity_ch2.temperature` | history, real_time | str | `76.9`, `76.8`, `76.6` | `ºF` | 0/285 | yes |
| `data.temp_and_humidity_ch3.humidity` | history, real_time | str | `51`, `52`, `53` | `%` | 0/285 | yes |
| `data.temp_and_humidity_ch3.temperature` | history, real_time | str | `72.5`, `72.4`, `72.8` | `ºF` | 0/285 | yes |
| `data.wind.wind_direction` | history, real_time | str | `350`, `357`, `352` | `º` | 0/285 | yes |
| `data.wind.wind_gust` | history, real_time | str | `4.7`, `4.9`, `4.5` | `mph` | 0/285 | yes |
| `data.wind.wind_speed` | history, real_time | str | `2.5`, `2.1`, `2.2` | `mph` | 0/285 | yes |

## Endpoint asymmetry

**Present in real-time but not history (3):**

- `data.battery.temp_humidity_sensor_ch1`
- `data.battery.temp_humidity_sensor_ch2`
- `data.battery.temp_humidity_sensor_ch3`

## Fields that never varied

Constant across every observation. Candidates for placeholder or
zero-filled channels rather than real attached sensors — but a genuinely
still sensor looks identical over a short window, so this is a flag for
review, not a conclusion.

- `data.battery.soilmoisture_sensor_ch1` (always `1.6`)
- `data.battery.soilmoisture_sensor_ch2` (always `1.6`)
- `data.battery.temp_humidity_sensor_ch1` (always `0`)
- `data.battery.temp_humidity_sensor_ch2` (always `0`)
- `data.battery.temp_humidity_sensor_ch3` (always `0`)
- `data.rainfall_piezo.1_hour` (always `0.00`)
- `data.rainfall_piezo.daily` (always `0.00`)
- `data.rainfall_piezo.event` (always `0.00`)
- `data.rainfall_piezo.monthly` (always `0.00`)
- `data.rainfall_piezo.rain_rate` (always `0.00`)
- `data.rainfall_piezo.yearly` (always `0.05`)
- `data.soil_ch2.soilmoisture` (always `18`)

## Values that do not parse as float

None — every observed value parsed.

## Notes for the user

- `soil_chN.ad` is an unexplained raw ADC-style reading alongside
  `soilmoisture`. Its meaning and scale need confirming before it is
  stored as anything but an opaque number.
- `outdoor.vpd` (vapour pressure deficit) is reported in `inHg` and is
  **not** in the published field list.
- `rainfall_piezo.1_hour` is named `hourly` in the published docs. The
  wire name is authoritative.
- `battery.*` mixes volts with unitless status codes; the unitless ones
  are not measurements and should not be resampled.
