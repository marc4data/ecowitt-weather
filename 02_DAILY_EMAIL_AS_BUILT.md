# Daily lakehouse email — as built

> **Companion to [01_DAILY_EMAIL_REQUIREMENTS.md](01_DAILY_EMAIL_REQUIREMENTS.md).**
> Written 2026-09-03. The system has been sending unattended since 2026-08-29.
>
> The spec was written before anything was built. This records **where the built
> thing differs from it, and why** — so the spec can be read as history rather
> than as a description of what is running.

---

## 1. Deviations that change what a reader sees

### 1.1 The subject line was rewritten

**Spec (§6.1):** `[lakehouse] OK - Thu 27 Aug - high 102F, low 72F, all checks passed`

**Built:**

```
Lake house Ecowitt System checks are good for Wed, Sep 2nd
Lake house Ecowitt System checks need ATTENTION for Fri, Aug 21st - 2 issues, indoor 94.8 ºF
REPLAY — Lake house Ecowitt System checks are good for Tue, Sep 1st — not current conditions
```

The bracketed prefix was borrowed from cfdb, where the audience is one engineer
who wants to filter and sort. Here two of the three readers are not technical,
and `[lakehouse] OK -` reads as machine output. The high/low were dropped from
the subject because they are the first thing in the body and a phone
notification truncates.

What survived, because it is load-bearing: **ATTENTION is capitalised and "good"
is not** (the shape of the word is caught before it is read), and **REPLAY leads**
(a truncated subject keeps its beginning).

### 1.2 The timezone is no longer printed — a deliberate break with §8.7

The spec required *"All times in `America/Chicago`, stated once in the email."*
The zone is no longer printed at all. Three readers who know where the house is
do not need `America/Chicago` on a line that says 6:40 AM.

Every timestamp is still **converted** through that zone; only the label is gone.

In its place is something more useful: **"The station reports every 5 minutes.
Each figure above is a single reading and the time it happened — not an
average."** That sentence exists because of §2.1 below.

### 1.3 Times are 12-hour and right-aligned

Not specified. `6:40 AM` sits under `10:00 PM` on the colon, which is only
possible with right alignment and no zero-padded hour.

### 1.4 The summary table gained dew point, and Title Case

Dew point high and low were added **above** the humidity rows: relative humidity
of 40% means something different at 105 ºF than at 70 ºF, while a dew point of
70 ºF is muggy at any temperature. Labels went to `Outdoor High` from
`outdoor high`, and the table was capped at 340px — full width put a label and
its number at opposite ends of a phone.

### 1.5 Six charts, not three

**Spec (§6.4):** indoor (30 days), outdoor + humidity (7 days), battery (30 days).

**Built:**

| Chart | Window | Change from spec |
|---|---|---|
| Outdoor temperature | 7 days | humidity panel **removed**; every day's high and low marked and labelled |
| Daily outdoor range | 4 weeks, Mon–Sun | **new** — bars low→high, integers labelled, no zero baseline |
| Rain by the hour | 7 days | **new** |
| Indoor temperature | 7 days (was 30) | band shading **replaced** by labelled limit lines; console trace removed; hourly averages; legend by room name |
| Indoor humidity | 7 days | **new** |
| Battery | 30 days | unchanged — still only when a battery check is not green |

The band shading was removed because a tint behind the traces muted the traces
it was supposed to frame, and made a normal day look like a warning.

Total email ≈ 200 KB against the spec's 1 MB ceiling.

### 1.6 Claude writes two paragraphs, not three

**Spec (§6.3):** triage writes *what is wrong*, *since when*, and *what to do*.

**Built:** it writes *what happened* and *what it means*. **It is explicitly
forbidden from writing "what to do."**

The email already builds a what-to-do section from the failing checks and the
configured contacts — real phone numbers, advice written once and reviewed.
Printing a model's paraphrase above it made the same email say the same thing
twice, the second time less precisely. On one real run the two disagreed: Claude
suggested sending someone "this week" while the configured action said check the
breaker and named three people.

**Claude describes; the code prescribes.**

### 1.7 The contact list is gated on whether the house is the problem

Not specified. Contacts appear **only when a house check fails**, never for a
data failure.

Found by replaying 1 August, whose only failure was "no ingestion run covered
this window" — the pipeline did not exist yet — and whose email told three people
to call an HVAC company about a cron job. Sending a neighbour to an empty house
because a scheduled job missed is worse than saying nothing, and after it happens
once nobody believes the next one.

### 1.8 A priority order decides which failure leads

Not specified. When several checks fail, the subject and the "what is wrong" list
are ordered: **is the house all right → can we still see the house → is the data
fit to answer either question.**

Without it, 21 August — a day the house sat at 93 ºF — led with an irregular rain
accumulator, because that check happens to run earlier.

---

## 2. Findings that corrected the spec

### 2.1 Chart peaks contradicted the summary table

The 7-day charts were built from **hourly means**, so 5 August drew and labelled
its peak as 104 ºF while the table said 105.3 ºF. Both were right; nothing told
the reader which was an aggregate. The 3 pm hour ran 103.0–105.3 and averaged
103.8.

Fixed at the source: the 7-day frame is now fetched at the station's native
5-minute resolution, so the labelled peak *is* the reading the table quotes. The
indoor charts, which are deliberately hourly for legibility, now say **"hourly
averages"** in their titles.

### 2.2 The A/C failure ran 13–27 August, not 9–27

**Spec (§4, §10-G):** indoor ran "roughly 93–100 ºF for about two weeks from
~9 August", and Phase G's acceptance test was that the new check fires 9–27.

**Measured:** indoor was 74–75 ºF on 9–11 August. The first hour above 85 ºF is
**13 August**; the peak was **96.2 ºF**, not 100; cooling was restored during
**27 August**.

The new check reproduces exactly 13–27 and fires on no earlier day. **The
acceptance criterion should read 13–27 August.**

### 2.3 §8.8's DST guarantee was not actually holding

The spec said `run_checks` "already computes `expected` from the bounds rather
than assuming 288. Do not regress this." It was already wrong.

Python subtracts two aware datetimes that share a `tzinfo` by **wall clock**, so
the span across both midnights of 1 November 2026 came back as exactly 24 h,
while the grid correctly held **300** five-minute slots. Coverage would have read
300/288 = 104.2%, and a genuine hour-long hole on the one day a year the
arithmetic differs would have been invisible underneath it.

Pre-existing bug, not introduced by this work. Fixed, with a test.

### 2.4 `no flatlined sensor` was removed

**Spec (§7.1)** listed it among the checks inherited unchanged.

Measured against the station's own history it warned on **4 of 27 days**, every
one a coarsely quantised sensor doing exactly what it should — soil moisture
reads in whole percent, so a still day genuinely holds one value. It was the
largest single source of WATCH emails.

A warning that is usually nothing is worse than no warning: it teaches three
people to skim, and the one that matters then arrives looking like the ones that
did not. Removing it took completely-clean days from **2 of 27 to 5 of 27**.

The failure it was meant to catch — a sensor that has stopped updating — is
covered better by `sensors reporting recently`, which measures the age of the
last reading and does not depend on the value changing.

**Check count is now 14, not 15.**

---

## 3. Open questions, answered

| Spec | Question | Answer |
|---|---|---|
| §11.1 | Soil-sensor reporting resolution | **0.1 V steps.** ch1 has read exactly 1.60 V for its whole life; ch2 has shown only 1.60 and 1.70. Two observable steps between fresh and the 1.40 V warning. No threshold buys more notice — it is a property of the sensor, and the check now says so in its note rather than implying confidence. WS90 cell reports at ~0.01 V, its capacitor at 0.1 V. |
| §11.2 | Send time | **07:00 America/Chicago**, after the 10:00 UTC reconcile pass. The timer states the zone explicitly; the VM clock is UTC. |
| §11.3 | What the channels are | **ch1 = Basement, ch2 = Living Room, ch3 = Office/Bedroom.** Defined once, in `ecowitt_nb.ROOM_NAMES`, applied to the `location` field every consumer already reads. **The two soil channels remain unidentified** and keep their `ch1`/`ch2` labels. |
| §11.4 | Is there heat in winter | **Yes.** The 45 ºF floor is a real setpoint, not an assumption. Had the house been winterised and drained, the cold check would have had to be about confirming it stayed drained. |
| §11.5 | What to do, and who | Provided, and moved **out of the repo** — see §5.1. |
| §11.6 | Stacy's and Tad's addresses | Provided; in the systemd unit, not the code. |
| §11.7 | Does everyone want the equipment section | **Not asked.** It collapses to one line when green, which the spec allowed. |

---

## 4. Built beyond the spec

| Addition | Why |
|---|---|
| `python -m reporting.matrix` | Every check × every day as one grid, with a "not PASS" rate per row. It is what made the case for removing `no flatlined sensor` — a daily email cannot show you which checks are merely loud. |
| `python -m reporting.triage --check` | Reports the Claude configuration and makes one live call, turning a failure into the fix rather than a stack trace. |
| `--selftest` | A synthetic ACTION email needing no database, so "the alerting works" is demonstrated rather than assumed. The spec asked for the DAG; the CLI flag came with it. |
| `infra/run_as_unit.sh` | Runs the report with the environment **read back out of systemd**. Retyping the addresses by hand is how a defect got in (§5.3). |
| `infra/create_emailer_user.sh`, `create_report_secrets.sh` | The spec left `email_log` and its role as commented SQL. These apply it, create the role, and verify the role is genuinely narrow. |
| Deploy proves before enabling | `deploy_report.sh` installs with the timer **off**, runs a real verification, and enables only on success. A scheduler enabled for something that has never run first executes unattended at 07:00. |
| `UNIQUE (for_date, mode)` on `email_log` | Idempotency is **structural**, not procedural. Verified: a second production row for the same day is refused by the database. |
| `Reply-To` | Added with the sender change (§5.4). |

---

## 5. Security and privacy work the spec did not anticipate

### 5.1 Contacts never enter the repository

They were briefly pasted into `config.py`. That file is destined for a public
repo, and the entries are other people's names and phone numbers plus a note
about who knows where the key to an empty house is hidden.

They now come from `LAKEHOUSE_CONTACTS` — Secret Manager on the VM, gitignored
`.env` locally. §10's rule ("secrets never enter the repo") applies at least as
strongly to a neighbour's phone number as to a database password.

### 5.2 Location details were removed or scrubbed

Coordinates were replaced with a region name in the requirements doc, in
`config.py`, and in a Phase 0 report that carried them in a footnote about the
altitude offset. `data/` and `notebooks/_prerefactor/` were gitignored — the
first holds recipient addresses and rendered reports on an empty house, the
second had the console MAC embedded in saved notebook output.

The station URL and the Anthropic workspace id are substituted at deploy time
rather than committed.

### 5.3 Three deployment defects, each caught before it reached anyone

| Defect | Symptom it would have produced |
|---|---|
| Database password interpolated into a URL unencoded | `failed to resolve host 'xyz!@127.0.0.1'` — the password contained `!` and `@`. Never appeared locally because the notebook path uses `quote_plus`. |
| `.env` inline comments not stripped | `# the household` glued onto the last address in the To: header. python-dotenv strips them; a hand-rolled shell parser did not; systemd does not either. |
| A `#` in a *comment* matched the placeholder guard | Install aborted with "a placeholder survived substitution" when nothing had. |

All three were found by the verification step, not in production.

### 5.4 The sender moved to a dedicated account

Sending from a personal Gmail filled its Sent folder. Now
a dedicated automation account (`Lake House Monitor <…>`), which required three things the
spec did not contemplate:

- **`Reply-To`** pointing at a real person. The footer says "tell Marc"; without
  this, replying to an unattended mailbox is the same as doing nothing.
- **A separate SMTP username.** A display name is valid in `From` and invalid as
  a Gmail login; the failure is a bare authentication error at 07:00. It now
  refuses up front with a message naming the fix.
- **Quoted `Environment=` lines.** systemd splits on whitespace, so
  `Lake House Monitor <…>` would have set the variable to `Lake`.

### 5.5 The house band was rebuilt without CSS positioning

The band-with-a-dot used three absolutely-positioned `<div>`s. **Gmail strips
`position:` entirely**, so it arrived as broken fragments above an empty box —
live for six days, and only visible in a real mail client. It is now percent-width
table cells.

`render.py`'s own docstring said "no flex, no grid" and then used absolute
positioning three lines later. **A browser render is not a test of an email.**

---

## 6. Not yet done

| Item | Status |
|---|---|
| §12 — stopping the timer produces a Cloud Logging alert, **verified by stopping it** | **Not done.** The heartbeat query and threshold are in place and the email-staleness check is live, but the switch has never been tripped. A switch nobody has tripped is a switch nobody knows the state of. |
| ACTION email delivered from the VM | **Not done.** `--selftest --test` has never run there. It is the path that only executes on a bad morning, so it is the least exercised code in the system. |
| Airflow DAG (Phase D) | Written (`dags/lakehouse_daily_dag.py`), never installed into the cfdb Airflow. It calls the same entry point as the timer and sends `--test`, deliberately. |
| Soil channel identification | Still unknown; those two keep channel labels. |
| Everything committed to git | **Nothing from this project is committed.** The running production system was deployed from a working tree on one laptop. |

---

## 7. What is actually running

- **`ecowitt-report.timer`** on `ecowitt-db`, 07:00 America/Chicago, enabled.
- **Six consecutive production emails**, 29 August – 3 September, all `ok`,
  firing between 07:01 and 07:05.
- Three roles: `ecowitt` (owner), `ecowitt_ro` (read-only), `ecowitt_emailer`
  (INSERT/SELECT on `email_log` and nothing else — verified).
- Five secrets in Secret Manager, fetched at runtime, never written to disk.
- **101 tests**, ruff clean.
