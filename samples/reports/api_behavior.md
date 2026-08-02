# D4 — API behavior notes

Generated 2026-08-02T05:56:08.398162+00:00

## Unit parameters (§8)

Valid ranges were not taken from the documentation. Each was obtained by
sending an out-of-range value and reading the range back out of the API's own
error message, then sweeping it.

| parameter | valid IDs | ID → unit | parameter honored? |
|---|---|---|---|
| `temp_unitid` | 1–2 | `1` → `℃`<br>`2` → `ºF` | yes |
| `pressure_unitid` | 3–5 | `3` → `hPa`<br>`4` → `inHg`<br>`5` → `mmHg` | yes |
| `wind_speed_unitid` | 6–11 | `6` → `m/s`<br>`7` → `km/h`<br>`8` → `knots`<br>`9` → `mph`<br>`10` → `BFT`<br>`11` → `fpm` | yes |
| `rainfall_unitid` | 12–13 | `12` → `mm`, `mm/hr`<br>`13` → `in`, `in/hr` | yes |
| `solar_irradiance_unitid` | 14–16 | `14` → `lx`<br>`15` → `fc`<br>`16` → `W/m²` | yes |
| `capacity_unitid` | 24–26 | `24` → —<br>`25` → —<br>`26` → — | not observable on this station |

### Exact encodings

Unit strings become stored values, so they must round-trip byte-for-byte.

| unit | non-ASCII codepoints |
|---|---|
| `BFT` | ascii |
| `W/m²` | U+00B2 |
| `fc` | ascii |
| `fpm` | ascii |
| `hPa` | ascii |
| `in` | ascii |
| `in/hr` | ascii |
| `inHg` | ascii |
| `km/h` | ascii |
| `knots` | ascii |
| `lx` | ascii |
| `m/s` | ascii |
| `mm` | ascii |
| `mm/hr` | ascii |
| `mmHg` | ascii |
| `mph` | ascii |
| `ºF` | U+00BA |
| `℃` | U+2103 |

> ⚠️ **The API is not internally consistent about degree signs.**
> `temp_unitid=1` returns `℃` (U+2103 DEGREE CELSIUS) while `temp_unitid=2`
> returns `ºF` (U+00BA MASCULINE ORDINAL INDICATOR + `F`) — two different
> conventions from the same parameter. The published example response also
> shows `℉` (U+2109) for a sub-device while using `ºF` for the main groups,
> and mixes `µ` (U+00B5 MICRO SIGN) with `μ` (U+03BC GREEK SMALL LETTER MU).
> Do not normalise these. Compare exactly, store exactly.

## Unit ID numbering

IDs are globally unique across parameters rather than per-parameter, and the
observed families leave **17–23 unaccounted for**, implying unit parameters
this project has not identified. `capacity_unitid` (24–26) was found by
guessing the name, so name-guessing is the only discovery route for the gap.
Absence of evidence here is not evidence of absence.
