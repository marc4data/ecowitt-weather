# Daily lakehouse email — requirements

> **Status: drafted 2026-08-28, revised 2026-08-28, not yet built.** Written to
> be handed to Claude Code.
>
> Sections marked **TBD** are unresolved. Following this repo's own convention
> (CLAUDE.md preamble): **do not invent answers for them.** If a task depends on
> an unresolved item, stop and ask.

---

## 1. What this is

A daily email to three people — Marc, Stacy (sister), Tad (cousin) — answering
one question about the lakehouse in rural Oklahoma:

**Is the house all right?**

Two shapes, same address list:

- **The usual one.** Everything is working. Yesterday's highs and lows, and
  enough trend to notice drift. Should be readable in ten seconds on a phone.
- **The other one.** Something needs a person. What is wrong, since when, the
  data that says so, and what to do about it.

The default is the first. The second has to be rare enough that its arrival
means something, and reliable enough that its absence does too.

### 1.1 Scope — settled

`CLAUDE.md` §1 previously excluded "any dashboard or UI" from scope. **That
bullet was removed on 2026-08-28**, which clears the way for this work.

The remaining exclusion — *"Weather-condition alerting (this is not a warning
system)"* — **stands, and this project does not violate it.** Nobody is being
warned about a thunderstorm. This reports on the **house and the
instrumentation**: whether cooling is holding, whether sensors are reporting,
whether batteries are alive. That is a different subject from forecasting
weather, and the distinction is worth stating plainly in the code so a future
reader does not have to re-litigate it.

**Build under `reporting/` in this repo**, not in a sibling repo.
`ecowitt_daily.attention()` already exists and carries the docstring *"What a
daily email keys off"* — the coupling is real whether or not a repo boundary
admits it, and two copies of the check thresholds is exactly the failure this
project keeps designing against.

---

## 2. Decisions made

| Question | Decision |
|---|---|
| Recipients (production) | Marc, Stacy, Tad — **all three, every email**, green or red |
| Recipients (test) | **Marc only**, always, under every circumstance (§5) |
| Reporting date | **Yesterday by default**, any date on request (§5) |
| Indoor policy | **Minimum-protection setpoint**, not comfort: 85 °F ceiling / 45 °F floor / RH under 65 % |
| Battery chemistry | **Alkaline throughout. No lithium anywhere in the system.** |
| Email transport | **Gmail SMTP + app password**, via the `src/alerting.py` pattern from `ncaa_football/claude_code` |
| Charts | **Inline PNGs as CID attachments** — render without a click, no login |
| Scheduler (dev) | **Airflow 3.3.1 on the Mac**, the existing cfdb Docker Compose stack |
| Scheduler (prod) | **systemd timer on `ecowitt-db`**, a fifth beside ingest / reconcile / backup / heartbeat |

### 2.1 Why the scheduler is split

Airflow is the resume artifact; the systemd timer is what actually has to fire.

The cfdb Airflow runs in Docker Compose **on the Mac**. It is a real Airflow 3
deployment — LocalExecutor, dedicated dag-processor, DAGs served from a git
worktree pinned to `main`, secrets from `.env`, `on_failure_callback` wired into
every DAG's `default_args`. That is a legitimate thing to talk about in an
interview and it is worth building this DAG there.

It is also on a laptop that sleeps, and `infra/tunnel.sh` **refuses to run
anywhere but a workstation** — so both the scheduler and the database connection
are best-effort by construction. For college football data, a missed run costs a
stale line. Here, the run that does not fire is the morning the A/C is dead.
That is precisely the failure mode `infra/README.md` built two Cloud Logging
policies to prevent, and it would be strange to reintroduce it for the alert
that matters most.

So:

- **On the Mac (Airflow):** the DAG, developed and demonstrable, running against
  the tunnel when the tunnel is up. Portfolio, and a genuinely useful dev loop.
- **On `ecowitt-db` (systemd):** `python -m reporting.daily --send`, timer
  semantics identical to the four already there, connecting to Postgres over the
  unix socket with no tunnel at all.

**The same entry point, invoked two ways.** The DAG is a `PythonOperator` calling
the same `reporting.daily` module the timer calls. Nothing about the report
knows which one invoked it. If that stops being true, the Airflow version stops
being a demonstration of the production path and becomes a second
implementation — which is the thing to watch for in review.

---

## 3. What already exists — reuse, do not rebuild

### 3.1 In this repo (`ecowitt_weather`)

| Asset | What it gives us |
|---|---|
| `notebooks/ecowitt_daily.py` → `run_checks()` | Ten day-scoped boundary checks, each returning verdict + measured + why |
| → `attention()` | Severity / headline / items, written for this email specifically |
| → `rolling_checks()` | The same checks across N days, one query — the "has it been drifting" view |
| → `headlines()` | The twelve summary numbers **with the time each happened** |
| `notebooks/ecowitt_nb.py` | Connection, palette, `fetch_window`, `fetch_periods`, `load_meta`, `logical_groups`, `plot_realm`, `wind_rose` |
| `schema/metric_catalog_seed.sql` | `kind` and `resample_rule` per metric — the email must respect these (no mean of an accumulator) |
| `infra/heartbeat.sh` | The dead-man's-switch pattern to extend (§9) |
| Cloud Logging policies | *pipeline reporting unhealthy* + *pipeline is not reporting* (fires on **absence**) |

### 3.2 In `ncaa_football/claude_code`

| Asset | What to take |
|---|---|
| `src/alerting.py` | Gmail SMTP send, `diagnose()` for SMTP errors, per-attempt dedup, **append-only JSONL fallback that always writes** |
| → `format_email()` | The pattern that matters: **a pure function**, so the exact email is testable and previewable with no scheduler and no network |
| `src/alert_triage.py` | Claude-written "what happened / impact / likely fix", wired as an *enhancement* that never blocks the send |
| `dags/alerting_selftest_dag.py` | A DAG that fails on purpose to prove alerts still arrive |
| `docker-compose.airflow.yml` | `DAGS_ARE_PAUSED_AT_CREATION: "false"` and the pinned-worktree volume mounts |

**Take the shape, not the file.** `src/alerting.py` sends `message.set_content(body)`
— plain text only. This email needs `multipart/alternative` (text + HTML) wrapped
in `multipart/related` (for the CID images). That is a real change, but the three
things worth copying survive it intact: the pure formatter, the local log that is
written *before* anything networked is attempted, and the rule that **nothing in
the alert path may raise.**

---

## 4. The gap this project exists to close

The indoor temperature ran roughly 93–100 °F for about two weeks from ~9 August,
and nothing said so.

That is not a bug in `indoor climate holding`. That check is deliberately keyed
to a **sustained climb** — hourly means rising ≥4 °F without reversing — because
it was calibrated against a real A/C failure (9.27 °F over nine hours) versus
normal compressor cycling, and a plain rate threshold could not separate them.
The reasoning in the module is sound and the calibration numbers are real.

But **a house that is already hot is not climbing.** Flat at 95 °F produces no
run of rising hourly means, so the check passes, correctly, every day. There is
no absolute band check on indoor temperature anywhere in the project.

The two checks do different jobs and both are needed:

- `indoor climate holding` — **early warning.** Catches cooling failing *while
  still in band*, hours before anything is uncomfortable. Keep it as it is.
- `indoor within protection band` (new, §7.2) — **the thing that must never be
  missed.** Catches the state, not the transition. Would have fired on day one
  of those two weeks and every day after.

---

## 5. Invocation, target date, and who gets the mail

This section is a **safety requirement**, not a convenience feature. The system
must make it difficult to accidentally send Stacy and Tad an alarming email
about a condition that is a week old.

### 5.1 The CLI

```
python -m reporting.daily                              # dry-run, yesterday, sends nothing
python -m reporting.daily --for-date 2026-08-21        # dry-run, that day
python -m reporting.daily --test                       # sends to Marc only, yesterday
python -m reporting.daily --test --for-date 2026-08-21 # sends to Marc only, that day
python -m reporting.daily --send                       # PRODUCTION: yesterday, all three
```

| Mode | Date | Recipients | Sends |
|---|---|---|---|
| default | yesterday | — | no; renders to disk |
| `--for-date D` | D | — | no; renders to disk |
| `--test` | yesterday or `--for-date` | **Marc only** | yes |
| `--send` | **yesterday only** | **all three** | yes |
| `--send --for-date D` | — | — | **refused** (§5.3) |

### 5.2 Two address lists, and no fallback between them

```
LAKEHOUSE_EMAIL_TO        # production — Marc, Stacy, Tad
LAKEHOUSE_EMAIL_TEST_TO   # test — Marc only
```

**Fail closed in both directions, and never substitute one for the other:**

- `--send` with `LAKEHOUSE_EMAIL_TO` unset → **refuse and exit non-zero.** Do not
  fall back to the test address. A production email that silently reached one
  person looks exactly like a production email that reached three.
- `--test` with `LAKEHOUSE_EMAIL_TEST_TO` unset → **refuse and exit non-zero.**
  Do not fall back to the production list. This is the asymmetry that matters:
  the cost of a test escaping to the family is much higher than the cost of a
  test not running.

Neither list is a default in code. An unset variable is a stop, not a guess.

### 5.3 Backfilled dates never go to production

`--send --for-date` is **refused** unless `--force-backfill-send` is also
present. The refusal message should say why rather than just erroring.

Why: the whole point of `--for-date` is to reproduce a past condition and look
at the email it produces. An ACTION email dated today but describing 21 August
tells three people the house is broken *now*. Best case that is confusing; worst
case somebody drives two hours to an empty house.

### 5.4 Any non-default date is visibly labelled

Every email built for a date other than yesterday carries a banner at the very
top of both the HTML and the text alternative:

```
REPLAY — this report covers Friday 21 August 2026.
It was generated on 28 August 2026 and does not describe current conditions.
```

Belt and braces: even if one escapes the guard in §5.3, no reader can mistake it
for today. The banner is part of `render()`, not the send path, so it is
impossible to send a replay without it.

### 5.5 Verifying the ACTION email

**21 August 2026 is the canonical verification date.** From the rolling checks
already run in `explore_daily.ipynb`, that day carries a genuine `FAIL` on
`rain accumulators only reset to zero`, plus `WARN` on `grid coverage` and
`longest single gap` — so it exercises the ACTION path against real stored data
rather than a fixture.

Two things to be precise about:

- As things stand today, 21 August produces a **data-quality** ACTION email, not
  a **house-emergency** one. It proves the shape, the routing and the severity
  mapping. It does not prove the wording of "the A/C appears to have stopped".
- Once `indoor within protection band` (§7.2) exists, 21 August will fail on
  *both* — it sits inside the 9–27 August indoor period. At that point one date
  exercises both paths, which makes it the right permanent smoke test.

```
python -m reporting.daily --test --for-date 2026-08-21
```

should land an ACTION email in Marc's inbox, labelled REPLAY, and reach nobody
else. Make that an acceptance criterion (§12), not a manual habit.

### 5.6 `email_log` records the mode

The mode is part of the record, not just the timestamp:

`email_log(sent_at, for_date, mode, severity, recipients, message_id)`

Two consequences, both load-bearing:

- **Idempotency keys on `(for_date, mode)`**, not `for_date` alone — so a test
  send does not block that day's production send.
- **The heartbeat staleness query filters `WHERE mode = 'production'`** (§9).
  Otherwise a test run at 3 pm resets the clock and masks a production email
  that never went out — an observability check defeated by the act of testing
  it, which is worse than not having it.

---

## 6. The email

### 6.1 Subject line

Follows the cfdb convention (`[cfdb] FAILURE - <headline>`) — a constant prefix
so a filter or a sort finds every one, then what actually happened, so the
subject alone is often enough.

```
[lakehouse] OK - Thu 27 Aug - high 102F, low 72F, all checks passed
[lakehouse] WATCH - Thu 27 Aug - indoor climbed 4.8F, no room agrees yet
[lakehouse] ACTION - indoor 96F for 14h - cooling appears to have stopped
[lakehouse] ACTION - no data since 03:15 Tue - station or pipeline is down
[lakehouse] REPLAY OK - Fri 21 Aug - test run, not current conditions
```

No emoji. Stacy and Tad should be able to tell from the notification alone
whether to open it now or later. Replay and test runs carry `REPLAY` in the
subject as well as the banner.

### 6.2 The usual email — structure

Reading order matters and is not negotiable: **the verdict comes first**, because
every number under it is only as good as the checks that produced it. This is
the same argument `explore_daily.ipynb` makes for putting boundary conditions
before the summary.

1. **One line.** `All systems go.` plus the single most interesting number.
2. **Yesterday.** The `headlines()` twelve — high, low, felt-hottest, humidity
   range, peak gust, peak solar/UV, pressure range, indoor high/low, rain total
   — **each with the time it happened.** Timing is half the story: 104 °F at
   15:00 is a summer afternoon, 104 °F at 03:00 is a broken sensor.
3. **How that compares.** Where yesterday sat against the last 7 and 30 days.
   One sentence, not a table: *"Warmest day in two weeks; indoor held steady."*
4. **Trend charts.** Three inline PNGs (§6.4).
5. **House status.** Indoor temp and humidity against the protection band, as a
   band-with-a-dot, not a number.
6. **Equipment.** One line per battery, only when something is not green;
   otherwise a single `All sensors reporting, batteries healthy.`
7. **Footer.** *"This arrives every morning at 07:00 Central. If it doesn't,
   something is wrong — tell Marc."* (§9 — the humans are part of the switch.)

### 6.3 The action email — structure

Same address list, different body. The rule is **conclusion, then evidence** —
never evidence and let the reader assemble the conclusion.

1. **What is wrong**, in a sentence a non-technical reader can act on.
   *"The lakehouse has been over 85 °F since Tuesday afternoon. The A/C does not
   appear to be running."*
2. **Since when**, with a real timestamp, not "recently".
3. **What to do**, naming who. **TBD** (§11.5) — this is the part that makes it
   an action email rather than a notification, and it cannot be written without
   knowing who can physically get to the house.
4. **The data that says so** — the relevant chart, and the failing check's
   `measured` and `note` fields, which already read as English sentences.
5. **What is still fine**, briefly. An alert that does not say what is *not*
   broken makes people assume everything is.
6. Then the usual digest underneath, unchanged.

**Claude triage (`alert_triage.py`) writes §1–§3 where it can, and the email
sends in its plain form when it cannot.** Same rule as cfdb: the summary is an
enhancement to the alert, never a precondition for it.

### 6.4 Charts

Three PNGs, embedded as CID parts, rendered with the existing `nb.plot_realm`
styling so they match the notebook:

| Chart | Content |
|---|---|
| `indoor.png` | Indoor temperature, 30 days, with the 45–85 °F protection band shaded. The one chart that answers the question this email exists to ask. |
| `outdoor.png` | Outdoor temperature and humidity, 7 days, the reported day highlighted — the context for everything else. |
| `battery.png` | Battery voltages, 30 days. Only attached when a battery check is not PASS. |

Constraints:
- **Total email under 1 MB.** Three PNGs at ~1000 px wide is comfortably inside.
- **Every chart must be readable in greyscale and legible at phone width.** The
  palette already assumes this (`ecowitt_daily.VERDICT_FILL` is tinted rather
  than saturated precisely so it survives a laser printer).
- **Gaps are drawn as gaps.** Never bridge a dropout with a line through
  readings that were not taken — the notebook is explicit about this and the
  email must not quietly regress it.
- **The text alternative must stand alone.** Gmail defers images from unfamiliar
  senders. If every image is blocked, the email must still deliver its verdict,
  its numbers, and — on a replay — its banner.

---

## 7. Detection rules

### 7.1 Inherited unchanged

Every check in `ecowitt_daily.run_checks()` runs as-is and feeds the email
through `attention()`. Nothing here re-implements them:

`grid coverage` · `longest single gap` · `day fully landed` · `runs covering the
day` · `rows quarantined` · `values corrected after the fact` · `no sensor
dropped out` · `no flatlined sensor` · `values physically possible` · `rain
accumulators only reset to zero` · `indoor climate holding` · `indoor humidity
in band`

### 7.2 NEW — `indoor within protection band`

The gap from §4. Add to `ecowitt_daily.run_checks()` so the notebook and the
email cannot disagree about it.

```python
# Minimum-protection setpoint, not comfort. The house is not being kept
# pleasant; it is being kept from damaging itself.
PROTECT_MAX_F = 85.0    # above this, sustained: cooling has stopped
PROTECT_MIN_F = 45.0    # below this, sustained: pipes are the concern
PROTECT_RH_MAX = 65.0   # condensation and mould, not comfort
PROTECT_HOURS = 3       # consecutive hourly means out of band
```

| | Condition | Verdict |
|---|---|---|
| Hot | hourly mean > 85 °F for ≥3 consecutive hours **and** ≥1 room channel also above 85 °F | **FAIL** |
| Hot | hourly mean > 85 °F for ≥3 consecutive hours, no room agrees | WARN |
| Cold | hourly mean < 45 °F for ≥3 consecutive hours | **FAIL** |
| Damp | any indoor RH > 65 % sustained ≥12 h | WARN |
| Damp | any indoor RH > 70 % sustained ≥12 h | **FAIL** |

Design notes, each there to stop a specific wrong answer:

- **Hourly means, not raw 5-minute readings.** Same reason `longest_climb()`
  resamples: a single spike is a sensor, three hours is a house.
- **`indoor.temperature` (the console) is authoritative**, and the paired
  channels only *corroborate*. This mirrors the existing check's calibration
  note — the console sits with the thermostat, and treating a sunny room as an
  equal voice produced a false positive the first time that check was written.
- **Corroboration is required on the hot side, not the cold side.** A single
  room baking in afternoon sun is not the house; a single room near an exterior
  wall running cold in January *is* an early sign, and the cost of being wrong
  is a burst pipe rather than an unnecessary phone call.
- **Persistence is on consecutive hours, not a daily count.** Three scattered
  hot hours across a day is weather leaking in; three in a row is a system.
- **The check must state which sensor and which hours**, not just a verdict —
  the action email's "the data that says so" section is built from `measured`.

Once this exists, **re-run it over all stored history** (1 August onward) and
confirm it fires on 9–27 August and does not fire before. A new check that
cannot reproduce the incident that motivated it is not yet calibrated.

### 7.3 NEW — battery

No threshold exists anywhere in the project today. Here is what the hardware
documentation says, and — separately — what it does not.

**The hardware.** Console is an HP2560 (`EasyWeatherPro_V5.2.2`). The metric
names identify the sensors: `haptic_array_*` is the WS90 7-in-1 (the haptic /
piezo rain array), and `battery.soilmoisture_sensor_ch1/ch2` are WH51-family
soil probes.

**Chemistry is settled: every cell in the system is alkaline. No lithium
anywhere.** That is what makes the voltage thresholds below usable — see the
warning at the end of this section for why it must stay true.

**Vendor-stated** — [WS90 manual](https://oss.ecowitt.net/uploads/20241106/WS90%20Manual.pdf),
[WH51 manual](https://oss.ecowitt.net/uploads/20251226/WH51Manual.pdf):

| Fact | Source |
|---|---|
| WS90 supercapacitor peak "should be above 3.5 v and lower than 5.5 v" | WS90 manual |
| WS90 capacitor "not overpassing 2.5 v" → inspect the top cover (solar panel) | WS90 manual |
| WS90 backup is 2×AA; solar panel 7.5 V ±5 % / 30 mA ±10 % | WS90 manual |
| WS90 operating range −40 °C to 60 °C (−40 °F to 140 °F) | WS90 manual |
| WH51 is 1×AA, "minimum 12 months" life | WH51 manual |
| WH51 operating range −10 °C to 50 °C (**14 °F to 122 °F**) | WH51 manual |

**Neither manual publishes a low-battery voltage for the AA cells.** The floors
below are therefore **derived from alkaline AA discharge behaviour, not from
Ecowitt**, and must be commented that way in the code so nobody later mistakes
them for a specification. Under a light load an alkaline AA reads ~1.60 V fresh,
~1.40 V around half spent, ~1.20 V nearly done, ~1.00 V cutoff.

| Metric | Sensor | Observed (30 d) | WARN | FAIL | Basis |
|---|---|---|---|---|---|
| `battery.haptic_array_capacitor` | WS90 supercap | 3.90 – 5.30 V | **daily peak** < 4.20 V | **daily peak** < 3.50 V | vendor |
| `battery.haptic_array_battery` | WS90 2×AA alkaline | 3.26 – 3.28 V | ≤ 2.70 V | ≤ 2.40 V | derived (1.35 / 1.20 V per cell) |
| `battery.soilmoisture_sensor_ch1` | WH51 1×AA alkaline | flat 1.60 V | ≤ 1.40 V | ≤ 1.20 V | derived |
| `battery.soilmoisture_sensor_ch2` | WH51 1×AA alkaline | flat 1.60 V | ≤ 1.40 V | ≤ 1.20 V | derived |

**The capacitor check is on the daily peak, not the instantaneous value.** It
swings roughly 4.0 → 5.3 V every day by design — solar charges it, night drains
it — so a raw threshold would alarm every night. The vendor's own phrasing is
about the *peak*. A peak that stops reaching ~5 V means the panel is dirty,
shaded, or failing, which is a real and fixable finding weeks before anything
stops reporting. Report the overnight minimum too: if it falls below 3.5 V
before dawn, the sensor is not banking enough charge to get through the night.

**Two things still to verify before trusting the soil numbers:**

1. **What is the reporting resolution?** The WS90 battery shows 3.26 / 3.27 /
   3.28 — about 0.01–0.02 V. But both soil probes read **exactly 1.60 V, min and
   max, for thirty days.** If the WH51 reports in 0.1 V steps, the entire useful
   range from fresh to dead is four observable values, and a 1.40 V WARN gives
   very little notice. Run this before fixing the numbers (§11.1):

   ```sql
   SELECT metric, value_num, count(*)
     FROM observation
    WHERE metric LIKE 'battery.soilmoisture%'
    GROUP BY 1, 2 ORDER BY 1, 2;
   ```

   If the answer is a single value, the thresholds are untested by construction
   and the check should say so in its `note` rather than implying confidence.
2. **A battery flat for 30 days and a battery reading that has stopped updating
   look identical.** The existing `no flatlined sensor` check cannot see this:
   it only examines `varying_kinds = {instantaneous, derived, extremum}`, and
   every battery metric is `kind='diagnostic'`. So add a companion check —
   **"battery voltage has not changed in N days"** — as an observation rather
   than an alarm. A genuinely fresh alkaline AA legitimately holds a step for
   weeks; the point is that the digest should say *"unchanged for 30 days"*
   rather than silently implying it was measured this morning.

> ⚠️ **These thresholds assume alkaline cells and break if that changes.**
> Lithium primaries hold a nearly flat curve for most of their life and then
> fall off a cliff, so a 1.40 V warning would arrive with almost no notice left.
> If the cells are ever replaced with lithium, the check must switch to **rate
> of fall** — any drop of more than one quantisation step within 48 hours —
> rather than level. Record the installed chemistry in a comment beside the
> constants so this coupling is visible at the point of change, not buried here.

**Seasonal note worth surfacing in the digest, not alerting on:** the WH51 is
rated only to 122 °F, and outdoor air hit 101.9 °F on 27 August. A dark probe
body in direct Oklahoma sun can exceed its rating without the air ever getting
close. If soil readings start behaving oddly on the hottest afternoons, that is
the first thing to check — and it is a placement problem, not a battery one.

### 7.4 NEW — sensor liveness, expressed as an age

`no sensor dropped out` compares yesterday against the day before, which answers
"did something disappear" but not "how long has it been gone". After two days a
dropped sensor stops being news to that check, because it is absent on both
sides of the comparison.

Add, per metric: **hours since the last non-null observation.** Report anything
over 6 h; FAIL anything over 24 h. This is the same argument `run_log` makes
about absence — a thing that has been missing long enough stops looking missing.

### 7.5 Severity and what it produces

`attention()` already returns `ok` / `warn` / `alert`. Map directly:

| Severity | Subject | Body | To |
|---|---|---|---|
| `ok` | `[lakehouse] OK - ...` | Digest (§6.2) | production list |
| `warn` | `[lakehouse] WATCH - ...` | Digest, with a "worth a glance" block above the fold | production list |
| `alert` | `[lakehouse] ACTION - ...` | Action email (§6.3), digest underneath | production list |

Recipient resolution is **always** §5.2 — severity never widens the audience,
and a test run never reaches the production list regardless of how bad the day
looks.

**One email per day per state.** If a FAIL persists for six days, six emails
arrive — that is correct, an unresolved failure is still news each morning — but
the body must say **"day 6 of this"**, because an alert that reads identically
on day 6 and day 1 trains people to skim. `attention()` already tracks
`resolved_earlier` for the inverse case; extend it to carry a run length.

---

## 8. Non-functional requirements

1. **Nothing in the send path may raise.** Carried over from `src/alerting.py`
   verbatim: an exception in the reporting path would mask the condition it
   exists to report. Every path wrapped, degrading to a printed warning.
2. **A no-data day still sends an email.** If the pipeline died, `run_checks()`
   returns 0 % coverage and `attention()` already returns `severity='alert'` with
   `'no data for the window'`. The email must go out saying plainly that the
   station or the pipeline is down. **Silence is never the report.**
3. **Idempotent.** Running twice for the same `(for_date, mode)` produces the
   same email and sends once (§5.6).
4. **Read-only against the observation data.** Connect as `ecowitt_ro`. The
   report has no business writing to `observation`, and
   `default_transaction_read_only` will enforce that anyway. `email_log` needs
   its own narrowly-granted writer — **do not widen `ecowitt_ro`.**
5. **`--dry-run` is the default and writes the email to a file.** Non-negotiable:
   the whole point of the pure-formatter pattern is being able to see tomorrow's
   email today, and making the harmless mode the default means a mistyped
   command does nothing rather than something.
6. **Respect `metric_catalog.kind`.** No mean of an accumulator, no linear mean
   of `wind_direction`, no interpolation of `soil.ad`. The rules are in the
   catalog; read them, do not re-derive them.
7. **All times in `America/Chicago`**, the console's own zone, stated once in the
   email rather than on every line. The station is in Oklahoma; Marc is on the
   west coast. Never mix them.
8. **DST-correct.** A 23- or 25-hour day is judged against its real length —
   `run_checks()` already computes `expected` from the bounds rather than
   assuming 288. Do not regress this. `--for-date 2026-11-01` must produce a
   25-hour window, and that is worth a test.
9. **`--for-date` must reject a future date and a date before 2026-08-01**, the
   start of history, with a message saying which it was.

---

## 9. The email that does not arrive

The hardest failure to see. If the DAG never runs, no email is sent, and an
absent email is invisible — the same class of failure `infra/README.md` calls
the project's primary risk, and for the same reason: **a dead scheduler produces
no errors, just silence and a green dashboard.**

Reuse the mechanism already proven here rather than inventing a second one:

1. A successful send writes an `email_log` row (§5.6).
2. `infra/heartbeat.sh` gains a sixth query: age of the newest **production**
   `email_log` row. `MAX_EMAIL_AGE_MIN=1560` (26 h — one daily plus slack),
   matching the existing `MAX_BACKUP_AGE_MIN` convention exactly.

   ```sql
   SELECT coalesce(round(extract(epoch from now()-max(sent_at))/60), -1)
     FROM email_log WHERE mode = 'production'
   ```

   **The `mode` filter is the whole point** — without it, testing the alerting
   silences the alarm that watches the alerting.
3. The existing *pipeline reporting unhealthy* policy then covers a stalled
   emailer, and *pipeline is not reporting* — which fires on metric **absence**
   — already covers a dead box. **No new alerting infrastructure is needed.**
4. And the footer in every email (§6.2) makes the three recipients the outermost
   layer of the same switch. Three people noticing that the morning email did
   not arrive is a cheaper and more reliable detector than anything on the VM.

Port `alerting_selftest_dag.py` as well: a manually-triggered path that produces
a synthetic ACTION email **to the test address**, so "the alerting works" is
something demonstrated rather than assumed.

---

## 10. Build order

Each phase is independently verifiable. Do not start the next until the previous
one can be demonstrated.

| Phase | Deliverable | Done when |
|---|---|---|
| **A** | `reporting/report.py` — `build_report(conn, date) -> Report`, pure, no email, no Airflow | `pytest` builds reports from fixture frames covering: clean day, no-data day, indoor-hot day, low-battery day, DST day |
| **B** | `reporting/render.py` — `render(report) -> (subject, text, html, images)`, pure | Renders all fixtures to files; text alternative readable with every image blocked; replay banner present whenever date ≠ yesterday |
| **C** | `reporting/send.py` — multipart send, two address lists, `email_log`, dedup, JSONL fallback | `--send --for-date` is refused; `--test` with an unset test address is refused; a forced SMTP failure still writes the JSONL record |
| **D** | `dags/lakehouse_daily_dag.py` on the Mac Airflow | Runs green against the tunnel; `on_failure_callback` wired; `catchup=False` |
| **E** | `infra/ecowitt-report.{service,timer}` on `ecowitt-db` | Fires on schedule, no tunnel, same entry point as D |
| **F** | `heartbeat.sh` extension + `email_log` staleness | Stopping the timer produces a Cloud Logging alert within the expected window — **verified by actually stopping it**, per the existing convention. A `--test` send does *not* clear the alarm. |
| **G** | Backfill the new checks over all history from 1 August | `indoor within protection band` fires 9–27 August and not before |

**Phase G is the acceptance test for §4.** If the new check cannot reproduce the
incident that motivated the whole project, it is not calibrated yet.

---

## 11. Open questions — TBD, do not invent

1. **Soil-sensor reporting resolution** — run the query in §7.3 before fixing any
   soil-battery threshold.
2. **Send time.** Proposal: **07:00 America/Chicago**, after the 10:00 UTC
   reconcile pass has rewritten any corrected values, so the email reports
   reconciled data rather than racing it. Confirm — and confirm this is a
   sensible hour for Stacy and Tad, who may not be in Central time.
3. **What are `temp_and_humidity` ch1 / ch2 / ch3, physically?** The email should
   say "the back bedroom", not "ch2". Same for `soil` ch1 / ch2.
4. **Is there heat at the house in winter?** The 45 °F floor assumes yes. If the
   house is winterised and drained instead, the cold-side check should be about
   confirming it stays drained, not about holding a temperature.
5. **What is the actual action for each alert, and who takes it?** Who is
   physically nearest, who holds a key, is there an HVAC company on file? §6.3
   cannot be written without this, and it is the difference between an action
   email and a notification.
6. **Stacy's and Tad's email addresses.**
7. **Does either of them want the equipment section at all?** A battery voltage
   is actionable for Marc and noise for everyone else. "All three, same email"
   is decided — this is only about whether §6.2.6 collapses to one line for
   readers who cannot act on it.

---

## 12. Acceptance criteria

- [ ] A clean day produces a single email whose verdict is legible in the
      subject line alone.
- [ ] A day with no data produces an email saying so — **not silence.**
- [ ] `--test --for-date 2026-08-21` lands an ACTION email in Marc's inbox,
      labelled REPLAY in both subject and body, and reaches nobody else.
- [ ] `--send --for-date` is refused with a message explaining why.
- [ ] `--send` with `LAKEHOUSE_EMAIL_TO` unset refuses rather than falling back
      to the test address; `--test` with `LAKEHOUSE_EMAIL_TEST_TO` unset refuses
      rather than falling back to the production list.
- [ ] A `--test` send does not clear the heartbeat's email-staleness alarm.
- [ ] The 9–27 August indoor period produces ACTION emails when replayed (§10-G).
- [ ] Every image blocked → the email still conveys verdict, numbers, action and
      replay banner.
- [ ] Stopping the timer produces a Cloud Logging alert, verified by stopping it.
- [ ] The default invocation with no flags sends nothing.
- [ ] The Airflow DAG and the systemd timer call **the same entry point**, and a
      reviewer can see that in one file.
- [ ] Derived battery thresholds are commented as derived and as
      alkaline-specific, with the vendor-stated numbers alongside for contrast.
