# lake — request register

Cowork owns this file. One row per request, minted the moment Marc makes it —
not when a round starts. Ids are `lake-<session>-R-###`; `R-###` is the short
form. Sessions: `main` (primary checkout).

Status key: ✅ landed · 🔨 in flight · 📋 queued · ⏸️ parked · 💭 deferred ·
❓ unverified · ⚠️ dropped

| ID | Request | Rounds | Notes |
|---|---|---|---|
| R-001 | **The rain chart reports a rate, not an amount** | 0 | Marc, 2026-09-17: *"Instead of it reporting the amount of rain in the observation (a 5-min snapshot). I'd like the chart to show rain total for a running 24 hours. So, rain totals accumulate for 24 hours then fall out of the calculation once the lag is outside the 24-hour window."* Measured: `src/reporting/charts.py::rain()` plots `rainfall_piezo.1_hour` resampled hourly, y-axis `in / hour`, 7-day window. Window stays 7 days — Marc, 2026-09-17, so it sits with the other three 7-day charts. 🔨 `lake-main-R-001`. Handoff is a file path, not a slash command — `project-round-close` is not installed in Claude Code (observed 2026-09-17); see CLAUDE.md §14. |
| R-002 | **`rainfall_piezo.1_hour` is a rolling window tagged as a resetting accumulator** | 0 | Found by Cowork 2026-09-17 while scoping R-001. Measured: `schema/metric_catalog_seed.sql:47` sets `kind='accumulator'`; `notebooks/ecowitt_daily.py:356-364` flags every accumulator fall that does not land on zero; `src/reporting/charts.py:369` documents `1_hour` as a **rolling** total, which decays to non-zero values by design. Production evidence — Sat 12 Sep email, all three cited samples are `rainfall_piezo.1_hour` at 15:15→0.08, 15:20→0.06, 15:25→0.05, on a day with 0.09 in of rain. **Hypothesis, not proven:** this accounts for the whole of the "6 irregular". The configured action text currently calls it "a known quirk of the piezo gauge" — if this holds, that sentence is wrong too. Note the constraint `metric_accumulator_needs_last` couples `kind` to `resample_rule`, so reclassifying is not a one-word change. 📋 |
| R-003 | **A data-only failure puts ATTENTION in the subject line** | 0 | From Cowork's 2026-09-17 review. Measured from Gmail: 5 of the last 14 delivered emails were ATTENTION — 9, 10, 11, 12, 13 Sep, consecutive. One (11 Sep, indoor +6.5 ºF, explained by Rich moving the thermostat) was a house event. Two were R-002. §1.7 already gates the contact list on whether a house check failed and §1.8 already ranks data last; the subject line reads neither. ⏸️ parked behind R-002, which may remove most of the volume on its own and change what this is worth. |
