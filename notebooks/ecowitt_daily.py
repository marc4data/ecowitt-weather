"""Day-scoped checks and summaries for explore_daily.ipynb.

Scope, deliberately narrow: **is one day's data fit to report on?**

That is a different question from `audit.ipynb`, which asks whether the whole
record holds up all-time -- run continuity, constraint integrity, credential
leakage, and whether curated rows can be re-derived from raw. Nothing here
duplicates those. These are the checks that decide whether the numbers printed
below them can be trusted for THIS day, and they lean on the boundaries: the
edges of the window, the edges of the grid, and the edges of each sensor's
physical range.

A check returns a verdict, a number, and a sentence. It never raises -- a
report that dies on its own health check tells you nothing about the weather.
"""

from __future__ import annotations

from datetime import timedelta, timezone

import pandas as pd
from ecowitt_nb import DISPLAY_TZ
from sqlalchemy import text

SLOT = pd.Timedelta(minutes=5)

# Physically impossible readings, by leaf metric. Deliberately generous: this is
# looking for a broken sensor or a unit change, not for unusual weather.
PHYSICAL_BOUNDS = {
    'temperature': (-60.0, 140.0),      # ºF
    'feels_like': (-80.0, 160.0),
    'app_temp': (-80.0, 160.0),
    'app_tempin': (-80.0, 160.0),
    'dew_point': (-80.0, 100.0),
    'humidity': (0.0, 100.0),           # %
    'soilmoisture': (0.0, 100.0),
    'wind_speed': (0.0, 200.0),         # mph
    'wind_gust': (0.0, 250.0),
    'wind_direction': (0.0, 360.0),     # º
    'solar': (0.0, 1500.0),             # W/m2
    'uvi': (0.0, 20.0),
    'absolute': (20.0, 35.0),           # inHg
    'relative': (20.0, 35.0),
    'rain_rate': (0.0, 20.0),           # in/hr
}



# --- indoor climate ---------------------------------------------------------
# A house with working air conditioning holds a setpoint: the temperature
# sawtooths as the compressor cycles, and any rise reverses within an hour or
# two. When cooling stops the sawtooth disappears and the indoor temperature
# climbs continuously toward outdoor.
#
# So the signal is the SUSTAINED climb, not the rate. Measured over nine days of
# this house: the largest continuous climb on a normal day was 2.88 ºF, while
# the afternoon the A/C tripped its breaker ran 9.27 ºF over nine hours. A
# plain rate threshold cannot separate those -- the fastest two-hour rise on a
# normal day (6.2 ºF) is almost the same as the failure's (6.7 ºF).
CLIMB_WARN_F = 4.0
CLIMB_FAIL_F = 6.0

# Comfort band. The upper bound is where condensation and mould risk start
# mattering, not merely where a room feels muggy.
INDOOR_RH_BAND = (25.0, 60.0)

# --- minimum-protection band ------------------------------------------------
# A DIFFERENT JOB from `indoor climate holding` above, and both are needed.
#
# That check is keyed to a sustained CLIMB, which is what catches cooling
# failing while the house is still in band -- hours before anything is
# uncomfortable. But a house that is already hot is not climbing. Flat at 95 ºF
# produces no run of rising hourly means, so it passes, correctly, every day.
# The indoor temperature ran roughly 93-100 ºF for about two weeks from 9
# August 2026 and nothing said so.
#
# This one catches the STATE rather than the transition. It is not a comfort
# setpoint: the house is not being kept pleasant, it is being kept from
# damaging itself.
PROTECT_MAX_F = 85.0     # above this, sustained: cooling has stopped
# Below this, sustained: pipes are the concern. ✅ Confirmed 2026-08-28 that the
# house IS heated in winter, so this is a real setpoint and not an assumption --
# the cold side asks "is the heat still holding", not "is it still drained".
# Had the house been winterised and drained instead, this check would have had
# to be about confirming it stayed drained, which is a different question.
PROTECT_MIN_F = 45.0
PROTECT_RH_WARN = 65.0   # condensation and mould, not comfort
PROTECT_RH_FAIL = 70.0
PROTECT_HOURS = 3        # consecutive hourly means out of band
PROTECT_RH_HOURS = 12    # damp is a slower failure than heat

# --- battery ----------------------------------------------------------------
# ⚠️ ONLY THE CAPACITOR NUMBERS ARE VENDOR-STATED. The WS90 manual says its
# supercapacitor peak "should be above 3.5 v and lower than 5.5 v", and that a
# capacitor "not overpassing 2.5 v" means inspecting the solar panel on the top
# cover. Neither the WS90 nor the WH51 manual publishes a low-battery voltage
# for its AA cells.
#
# The AA floors below are therefore DERIVED FROM ALKALINE DISCHARGE BEHAVIOUR,
# not from Ecowitt: under a light load an alkaline AA reads ~1.60 V fresh,
# ~1.40 V half spent, ~1.20 V nearly done, ~1.00 V cutoff. WS90 is 2xAA (so the
# per-cell figures double), WH51 is 1xAA.
#
# ⚠️ THESE ASSUME ALKALINE CELLS AND BREAK IF THAT CHANGES. Every cell in this
# system is alkaline; there is no lithium anywhere. A lithium primary holds a
# nearly flat curve for most of its life and then falls off a cliff, so a
# 1.40 V warning would arrive with almost no notice left. If the cells are ever
# replaced with lithium, this check must switch to RATE OF FALL -- any drop of
# more than one quantisation step within 48 hours -- rather than level.
#
# 'peak' compares the day's MAXIMUM, 'level' its minimum. The capacitor swings
# roughly 4.0-5.3 V every day by design (solar charges it, night drains it), so
# a level threshold would alarm every night; the vendor's own phrasing is about
# the peak, and a peak that stops reaching ~5 V means a dirty, shaded or failing
# panel weeks before anything stops reporting.
BATTERY_LIMITS = {
    'battery.haptic_array_capacitor':
        dict(mode='peak', warn=4.20, fail=3.50, basis='vendor', sensor='WS90 supercap'),
    'battery.haptic_array_battery':
        dict(mode='level', warn=2.70, fail=2.40, basis='derived', sensor='WS90 2xAA'),
    'battery.soilmoisture_sensor_ch1':
        dict(mode='level', warn=1.40, fail=1.20, basis='derived', sensor='WH51 1xAA'),
    'battery.soilmoisture_sensor_ch2':
        dict(mode='level', warn=1.40, fail=1.20, basis='derived', sensor='WH51 1xAA'),
}

# Measured from stored history on 2026-08-28, because a threshold is only as
# useful as the resolution underneath it:
#
#   battery.haptic_array_battery      3.26 / 3.27 / 3.28   -> ~0.01 V steps
#   battery.haptic_array_capacitor    3.40 .. 5.30         -> 0.1 V steps
#   battery.soilmoisture_sensor_ch1   1.60 only            -> 0.1 V steps
#   battery.soilmoisture_sensor_ch2   1.60 and 1.70        -> 0.1 V steps
#
# So a WH51 has TWO observable steps between fresh (1.6) and WARN (1.4), and one
# more to FAIL. That is very little notice, and it is a property of the sensor
# rather than of the threshold -- there is no number that buys more warning out
# of a 0.1 V quantisation. The check says so in its note rather than implying a
# confidence it does not have.
BATTERY_QUANTISATION_V = 0.1

# How long a battery reading may sit unchanged before the digest says so. Not an
# alarm: a fresh alkaline AA legitimately holds a step for weeks. The point is
# that "flat for 30 days" and "stopped updating" look identical, and the
# existing `no flatlined sensor` check cannot see it -- that one only examines
# instantaneous/derived/extremum metrics, and every battery metric is
# kind='diagnostic'.
BATTERY_STALE_DAYS = 30

# --- liveness ---------------------------------------------------------------
# `no sensor dropped out` compares yesterday against the day before, which
# answers "did something disappear" but not "how long has it been gone". After
# two days a dropped sensor is absent on both sides of that comparison and stops
# being news to it. An age does not decay like that.
LIVENESS_WARN_H = 6
LIVENESS_FAIL_H = 24


def indoor_sensors(meta, leaf='temperature'):
    """Every sensor inside the house: the console plus the paired channels."""
    return sorted(m for m, v in meta.items()
                  if v['leaf'] == leaf and v['realm'] in ('indoor', 'temp_and_humidity'))


def longest_climb(series):
    """Longest run of continuously rising hourly means: (hours, rise, start).

    Hourly means rather than raw 5-minute readings, so normal compressor
    cycling does not register as a climb.
    """
    hourly = series.resample('1h').mean().dropna()
    best_hours, best_rise, best_start = 0, 0.0, None
    run_start, run_len = None, 0
    for i in range(1, len(hourly)):
        if hourly.iloc[i] > hourly.iloc[i - 1]:
            if run_len == 0:
                run_start = hourly.index[i - 1]
            run_len += 1
            if run_len > best_hours:
                best_hours = run_len
                best_rise = float(hourly.iloc[i] - hourly.loc[run_start])
                best_start = run_start
        else:
            run_len = 0
    return best_hours, best_rise, best_start


def hourly_runs(series, threshold, above=True):
    """Longest run of consecutive hourly means past a threshold.

    Returns (hours, start, end); (0, None, None) when it never crosses.

    Hourly means rather than raw 5-minute readings, for the same reason
    `longest_climb` resamples: a single spike is a sensor, three hours is a
    house. Persistence is measured in CONSECUTIVE hours rather than as a daily
    count -- three scattered hot hours is weather leaking in when a door opens,
    three in a row is a system.
    """
    hourly = series.resample('1h').mean().dropna()
    past = hourly > threshold if above else hourly < threshold
    best, run, start = (0, None, None), 0, None
    for stamp, is_past in past.items():
        if not is_past:
            run, start = 0, None
            continue
        run += 1
        if run == 1:
            start = stamp
        if run > best[0]:
            best = (run, start, stamp)
    return best


def _verdict(ok, warn=False):
    return 'FAIL' if not ok else ('WARN' if warn else 'PASS')


def _worst(*verdicts):
    """FAIL beats WARN beats PASS, so one check can carry several conditions."""
    for level in ('FAIL', 'WARN'):
        if level in verdicts:
            return level
    return 'PASS'


def run_checks(conn, day, meta, start, end):
    """Every day-scoped boundary check, as one table.

    `day` is the wide 5-minute frame for the window; `start`/`end` are aware.
    """
    rows = []

    def add(name, verdict, measured, note):
        rows.append({'check': name, 'verdict': verdict,
                     'measured': measured, 'note': note})

    # --- the window itself --------------------------------------------------
    # Computed from the actual bounds rather than assumed to be 288, so a DST
    # day is judged against its real 23 or 25 hours.
    #
    # ⚠️ THE CONVERSION TO UTC IS LOAD-BEARING, and its absence was a bug.
    # Python subtracts two aware datetimes that share a tzinfo by WALL CLOCK,
    # not absolutely -- so `end - start` across both midnights of 1 November
    # 2026 returns exactly 24 h, while the grid `fetch_window` builds for the
    # same bounds correctly holds 300 five-minute slots. Coverage then read
    # 300/288 = 104.2%, and a genuine hour-long hole on the one day a year the
    # arithmetic differs would have been invisible underneath it.
    span = end.astimezone(timezone.utc) - start.astimezone(timezone.utc)
    expected = int(span / SLOT)
    present = int(day.notna().any(axis=1).sum())
    pct = 100.0 * present / expected if expected else 0.0
    add('grid coverage', _verdict(pct >= 90, warn=pct < 99),
        f'{present}/{expected} slots ({pct:.1f}%)',
        'below 90% is a FAIL; the cloud keeps 5-minute data for 3 months, so a '
        'gap found later may be unrecoverable')

    # Longest run of consecutive empty slots -- one 40-minute hole and eight
    # scattered singles both read as "97% covered", and they are not the same.
    empty = ~day.notna().any(axis=1)
    longest, current = 0, 0
    for is_empty in empty:
        current = current + 1 if is_empty else 0
        longest = max(longest, current)
    gap_min = longest * 5
    add('longest single gap', _verdict(gap_min <= 60, warn=gap_min > 15),
        f'{gap_min} min', 'a long hole distorts daily means; scattered singles do not')

    # Has the day finished landing? Reporting on a day the pipeline has not
    # finished writing produces numbers that change under you.
    last_seen = day.notna().any(axis=1)
    last_ts = day.index[last_seen][-1] if last_seen.any() else None
    tail_gap = None
    if last_ts is not None:
        tail_gap = (end.replace(tzinfo=None) - last_ts).total_seconds() / 60
    add('day fully landed',
        _verdict(tail_gap is not None and tail_gap <= 15, warn=False),
        f'last reading {tail_gap:.0f} min before midnight' if tail_gap is not None else 'no data',
        'the day should run to its final slot before it is reported on')

    # --- the pipeline over that window -------------------------------------
    runs = pd.read_sql(text('''
        SELECT status, count(*) AS n FROM run_log
         WHERE started_at >= :start AND started_at < :end
         GROUP BY status'''), conn, params={'start': start, 'end': end})
    by_status = dict(zip(runs.status, runs.n, strict=True)) if len(runs) else {}
    bad = {k: v for k, v in by_status.items() if k != 'succeeded'}
    add('runs covering the day', _verdict(not bad and by_status),
        ', '.join(f'{k}={v}' for k, v in sorted(by_status.items())) or 'no runs',
        'a failed or wedged run means the window may be incomplete')

    quarantined = conn.execute(text(
        'SELECT count(*) FROM quarantine WHERE ts_utc >= :start AND ts_utc < :end'),
        {'start': start, 'end': end}).scalar()
    add('rows quarantined', _verdict(quarantined == 0), str(quarantined),
        'rejected rows are kept, not dropped — a non-zero count needs a reason')

    changed = conn.execute(text(
        'SELECT count(*) FROM change_log WHERE ts_utc >= :start AND ts_utc < :end'),
        {'start': start, 'end': end}).scalar()
    add('values corrected after the fact', _verdict(True, warn=changed > 0), str(changed),
        'reconciliation rewriting many values is a signal, not routine')

    # --- the sensors --------------------------------------------------------
    # A metric that reported the day before and not this day is a sensor that
    # dropped out. Additions are commissioning and are fine; disappearances are
    # not (CLAUDE.md §4).
    prev = pd.read_sql(text('''
        SELECT DISTINCT metric FROM observation
         WHERE ts_utc >= :prev_start AND ts_utc < :start'''), conn,
        # Deliberately the WALL-CLOCK day before, not `span` before: the
        # comparison is "what reported yesterday", and yesterday is a calendar
        # day. Subtracting an absolute 25 h would start it at 23:00.
        params={'prev_start': start - timedelta(days=1), 'start': start}).metric
    today_metrics = {m for m in day.columns if day[m].notna().any()}
    dropped = sorted(set(prev) - today_metrics)
    add('no sensor dropped out', _verdict(not dropped),
        f'{len(dropped)} dropped' if dropped else 'none',
        ', '.join(dropped) if dropped else 'every metric reporting the previous day still reports')

    # ❌ REMOVED 2026-08-28: `no flatlined sensor`.
    #
    # It warned when an instantaneous metric held one value all day. The idea was
    # sound -- a stuck sensor reads as perfectly healthy in every coverage
    # metric -- but measured against this station's own history it was wrong far
    # more often than it was right: it warned on 4 of 27 days, every one of them
    # a coarsely quantised sensor doing exactly what it should. Soil moisture
    # reads in whole percent, so a still day genuinely holds one value.
    #
    # That made it the single largest source of WATCH emails, and a warning that
    # is usually nothing is worse than no warning at all: it teaches three people
    # to skim, and the one that matters then arrives looking like the ones that
    # did not. Removed rather than tuned, because the exclusion list needed to
    # make it quiet (every quantised metric) is most of what it was watching.
    #
    # The failure it was meant to catch -- a sensor that has stopped updating --
    # is covered better by `sensors reporting recently`, which measures the age
    # of the last reading and does not depend on the value changing.

    # --- the values ---------------------------------------------------------
    breaches = []
    for metric in today_metrics:
        leaf = meta.get(metric, {}).get('leaf')
        if leaf not in PHYSICAL_BOUNDS:
            continue
        lo, hi = PHYSICAL_BOUNDS[leaf]
        series = day[metric].dropna()
        out = series[(series < lo) | (series > hi)]
        if len(out):
            breaches.append(f'{metric} ({len(out)}× outside {lo}–{hi})')
    add('values physically possible', _verdict(not breaches),
        f'{len(breaches)} metric(s)' if breaches else 'all in range',
        '; '.join(breaches) if breaches else 'nothing outside its sensor range')

    # Rain accumulators only ever climb until they reset. A fall that is not a
    # reset to zero means a value went backwards, which rain cannot do.
    odd_resets = []
    for metric in sorted(today_metrics):
        if meta.get(metric, {}).get('kind') != 'accumulator':
            continue
        series = day[metric].dropna()
        drops = series.diff() < 0
        for stamp in series.index[drops]:
            if series.loc[stamp] > 0.001:      # a reset lands on zero
                odd_resets.append(f'{metric} at {stamp:%H:%M} -> {series.loc[stamp]}')
    add('rain accumulators only reset to zero', _verdict(not odd_resets),
        f'{len(odd_resets)} irregular' if odd_resets else 'none',
        '; '.join(odd_resets[:3]) if odd_resets else 'every fall is a reset, not a lost total')


    # --- the house ----------------------------------------------------------
    # The console's own sensor is the authoritative one: it sits with the
    # thermostat, so "is the house being cooled" means "is that reading
    # holding". The paired channels are rooms -- a sunny room baking on a hot
    # Saturday is not an A/C failure, and treating them as equals produced
    # exactly that false positive when this check was first calibrated.
    console = 'indoor.temperature'
    rooms = [m for m in indoor_sensors(meta) if m != console]

    if console in day.columns and not day[console].dropna().empty:
        hours, rise, began = longest_climb(day[console].dropna())
        agreeing = []
        for metric in rooms:
            if metric in day.columns and not day[metric].dropna().empty:
                _, room_rise, _ = longest_climb(day[metric].dropna())
                if room_rise >= CLIMB_WARN_F:
                    agreeing.append(meta[metric]['location'])

        failing = rise >= CLIMB_FAIL_F and agreeing
        warning = rise >= CLIMB_WARN_F
        detail = (f'+{rise:.1f} ºF over {hours} h from {began:%H:%M}'
                  if began is not None else 'no sustained climb')
        if agreeing:
            detail += f' · rooms agreeing: {", ".join(agreeing)}'
        if failing:
            note = ('cooling appears to have stopped — the thermostat-area reading '
                    'climbed without reversing and the rooms followed. Check the '
                    'A/C breaker.')
        elif warning:
            note = ('the thermostat area climbed further than a normal cycle but no '
                    'room corroborated it; watch rather than act')
        else:
            note = (f'setpoint held — any rise reversed within the hour. Normal here '
                    f'is under {CLIMB_WARN_F:.0f} ºF sustained; the afternoon the A/C '
                    'tripped ran 9.3 ºF')
        add('indoor climate holding',
            'FAIL' if failing else ('WARN' if warning else 'PASS'), detail, note)

    # The state, not the transition. See the PROTECT_* constants for why this
    # sits alongside `indoor climate holding` rather than replacing it.
    if console in day.columns and not day[console].dropna().empty:
        inside = day[console].dropna()
        hot_h, hot_from, hot_to = hourly_runs(inside, PROTECT_MAX_F, above=True)
        cold_h, cold_from, _ = hourly_runs(inside, PROTECT_MIN_F, above=False)

        # Corroboration is required on the HOT side only. A single room baking
        # in afternoon sun is not the house. A single room near an exterior
        # wall running cold in January IS an early sign, and the cost of being
        # wrong there is a burst pipe rather than an unnecessary phone call.
        agreeing = []
        if hot_h >= PROTECT_HOURS:
            for metric in rooms:
                if metric not in day.columns or day[metric].dropna().empty:
                    continue
                room_hourly = day[metric].dropna().resample('1h').mean()
                window = room_hourly.loc[hot_from:hot_to]
                if (window > PROTECT_MAX_F).any():
                    agreeing.append(meta[metric]['location'])

        temp_verdict, detail = 'PASS', None
        if cold_h >= PROTECT_HOURS:
            temp_verdict = 'FAIL'
            detail = (f'{inside.min():.1f} ºF — below {PROTECT_MIN_F:.0f} ºF for '
                      f'{cold_h} h from {cold_from:%H:%M}')
        elif hot_h >= PROTECT_HOURS:
            temp_verdict = 'FAIL' if agreeing else 'WARN'
            detail = (f'{inside.max():.1f} ºF — above {PROTECT_MAX_F:.0f} ºF for '
                      f'{hot_h} h from {hot_from:%H:%M}')
            detail += (f' · rooms agreeing: {", ".join(agreeing)}' if agreeing
                       else ' · no room agrees')

        # Damp is folded in here rather than given its own row because it is the
        # same question -- is the house being held somewhere it will not damage
        # itself -- on a slower clock. `indoor humidity in band` above is the
        # comfort bound and stays separate.
        damp_verdict, damp_detail = 'PASS', None
        worst_rh = None
        for metric in [m for m in indoor_sensors(meta, leaf='humidity') if m in day.columns]:
            series = day[metric].dropna()
            if series.empty:
                continue
            fail_h, fail_from, _ = hourly_runs(series, PROTECT_RH_FAIL, above=True)
            warn_h, warn_from, _ = hourly_runs(series, PROTECT_RH_WARN, above=True)
            if fail_h >= PROTECT_RH_HOURS:
                damp_verdict = 'FAIL'
                damp_detail = (f'{meta[metric]["location"]} over {PROTECT_RH_FAIL:.0f} % '
                               f'for {fail_h} h from {fail_from:%H:%M}')
                break
            if warn_h >= PROTECT_RH_HOURS and damp_verdict == 'PASS':
                damp_verdict = 'WARN'
                damp_detail = (f'{meta[metric]["location"]} over {PROTECT_RH_WARN:.0f} % '
                               f'for {warn_h} h from {warn_from:%H:%M}')
            worst_rh = max(worst_rh or 0, series.max())

        parts = [p for p in (detail, damp_detail) if p]
        if not parts:
            parts = [f'{inside.min():.1f}–{inside.max():.1f} ºF'
                     + (f', RH to {worst_rh:.0f} %' if worst_rh is not None else '')]
        add('indoor within protection band', _worst(temp_verdict, damp_verdict),
            ' · '.join(parts),
            f'minimum protection, not comfort: {PROTECT_MIN_F:.0f}–{PROTECT_MAX_F:.0f} ºF '
            f'and under {PROTECT_RH_WARN:.0f} % RH. Unlike `indoor climate holding` this '
            'catches a house that is ALREADY hot rather than one that is heating up — flat '
            'at 95 ºF is not a climb, so it needs its own check. The console reading is '
            'authoritative; a room must corroborate before heat is called a failure.')

    # --- the equipment ------------------------------------------------------
    offenders, observed = [], []
    for metric, limit in BATTERY_LIMITS.items():
        if metric not in day.columns:
            continue
        series = day[metric].dropna()
        if series.empty:
            continue
        value = series.max() if limit['mode'] == 'peak' else series.min()
        label = f'{metric.rsplit(".", 1)[-1]} {value:.2f} V'
        if (value < limit['fail'] if limit['mode'] == 'peak' else value <= limit['fail']):
            offenders.append(('FAIL', f'{label} ({limit["mode"]}) under {limit["fail"]:.2f}'))
        elif (value < limit['warn'] if limit['mode'] == 'peak' else value <= limit['warn']):
            offenders.append(('WARN', f'{label} ({limit["mode"]}) under {limit["warn"]:.2f}'))
        else:
            observed.append(label)
    if offenders or observed:
        add('battery levels',
            _worst(*(verdict for verdict, _ in offenders)),
            '; '.join(text for _, text in offenders) or ', '.join(observed),
            'capacitor thresholds are vendor-stated (WS90: peak should exceed 3.5 V); the '
            'AA floors are DERIVED from alkaline discharge behaviour and are not an Ecowitt '
            f'specification. The WH51 reports in {BATTERY_QUANTISATION_V:.1f} V steps, so '
            'there are only two observable steps between a fresh cell and a warning — treat '
            'the soil floors as untested rather than calibrated.')

    # A metric that has not reported for long enough stops looking absent to a
    # day-over-day comparison. An age does not decay.
    ages = pd.read_sql(text('''
        SELECT metric, max(ts_utc) AS last_seen FROM observation
         WHERE ts_utc < :end AND value_num IS NOT NULL GROUP BY metric'''),
        conn, params={'end': end})
    # Parsed rather than assumed: psycopg hands back aware datetimes, but the
    # fixture database the tests run against returns strings, and subtracting a
    # string from a timestamp is a crash inside a check that promises never to
    # raise.
    if len(ages):
        ages['last_seen'] = pd.to_datetime(ages['last_seen'], utc=True)
    stale = []
    for row in ages.itertuples():
        hours = (end - row.last_seen).total_seconds() / 3600
        if hours > LIVENESS_WARN_H:
            stale.append((hours, f'{row.metric} {hours:.0f} h'))
    stale.sort(reverse=True)
    worst_age = stale[0][0] if stale else 0.0
    add('sensors reporting recently',
        _verdict(worst_age <= LIVENESS_FAIL_H, warn=bool(stale)),
        f'{len(stale)} metric(s) stale · oldest {worst_age:.0f} h' if stale else 'all current',
        ('; '.join(text for _, text in stale[:4]) if stale else
         f'every metric reported within {LIVENESS_WARN_H} h of the end of the window — '
         'measured against the window, not the clock, so a replay of a past day still '
         'reports what was true then'))

    rh = [m for m in indoor_sensors(meta, leaf='humidity') if m in day.columns]
    levels = pd.concat([day[m].dropna() for m in rh]) if rh else pd.Series(dtype=float)
    if not levels.empty:
        lo, hi = INDOOR_RH_BAND
        breach = levels.max() > hi or levels.min() < lo
        # A comfort bound, so WARN rather than FAIL: muggy is not broken, and a
        # check that cries failure over humidity trains people to ignore it.
        add('indoor humidity in band', _verdict(True, warn=breach),
            f'{levels.min():.0f}–{levels.max():.0f} %',
            f'outside {lo:.0f}–{hi:.0f} % is a comfort and condensation concern; a '
            'sharp rise alongside a temperature climb points at cooling, not weather')

    frame = pd.DataFrame(rows)
    return frame[['check', 'verdict', 'measured', 'note']]


def verdict_banner(checks):
    """One line: is this day reportable?"""
    fails = (checks.verdict == 'FAIL').sum()
    warns = (checks.verdict == 'WARN').sum()
    if fails:
        return (f'NOT CLEAN — {fails} check(s) failed, {warns} warning(s). '
                'Read the failures before trusting anything below.')
    if warns:
        return f'USABLE — 0 failures, {warns} warning(s) worth a glance.'
    return 'CLEAN — every boundary check passed.'


# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------

def headlines(day, meta):
    """The handful of numbers that describe the day, with when they happened.

    Timing is half the story: a 104 ºF high at 15:00 is a normal summer day, the
    same high at 03:00 is a broken sensor.
    """
    def at(metric, how):
        if metric not in day.columns:
            return None, None
        series = day[metric].dropna()
        if series.empty:
            return None, None
        stamp = series.idxmax() if how == 'max' else series.idxmin()
        return series.loc[stamp], stamp

    def row(label, metric, how, fmt='{:.1f}'):
        value, stamp = at(metric, how)
        unit = meta.get(metric, {}).get('unit', '')
        return {'measure': label,
                'value': '—' if value is None else f'{fmt.format(value)} {unit}'.strip(),
                # 12-hour, and NOT zero-padded: '6:40 AM' reads as a time,
                # '06:40 AM' reads as a timestamp. Alignment is the renderer's
                # job -- right-aligning the column lines the colons up without
                # padding a leading zero onto the hour.
                'when': '—' if stamp is None else f'{stamp:%I:%M %p}'.lstrip('0')}

    out = [
        row('Outdoor High', 'outdoor.temperature', 'max'),
        row('Outdoor Low', 'outdoor.temperature', 'min'),
        row('Felt Hottest', 'outdoor.feels_like', 'max'),
        # Dew point above humidity, and deliberately so: it is the better
        # single number for how the air actually felt. Relative humidity of
        # 40% means something different at 105 ºF than at 70 ºF; a dew point
        # of 70 ºF is muggy at any temperature.
        row('Dew Point High', 'outdoor.dew_point', 'max'),
        row('Dew Point Low', 'outdoor.dew_point', 'min'),
        row('Humidity High', 'outdoor.humidity', 'max', '{:.0f}'),
        row('Humidity Low', 'outdoor.humidity', 'min', '{:.0f}'),
        row('Peak Gust', 'wind.wind_gust', 'max'),
        row('Peak Solar', 'solar_and_uvi.solar', 'max', '{:.0f}'),
        row('Peak UV Index', 'solar_and_uvi.uvi', 'max', '{:.0f}'),
        row('Pressure High', 'pressure.relative', 'max', '{:.2f}'),
        row('Pressure Low', 'pressure.relative', 'min', '{:.2f}'),
        row('Indoor High', 'indoor.temperature', 'max'),
        row('Indoor Low', 'indoor.temperature', 'min'),
    ]

    # Rain is an accumulator: the day's total is where it ended, not its mean
    # or its maximum.
    if 'rainfall_piezo.daily' in day.columns:
        series = day['rainfall_piezo.daily'].dropna()
        total = series.iloc[-1] if len(series) else None
        out.append({'measure': 'Rain Total',
                    'value': '—' if total is None else f'{total:.2f} in',
                    'when': 'end of day'})
    return pd.DataFrame(out)


def detail_table(day, meta, groups, slots):
    """Every series in the report, as numbers rather than a line on a chart."""
    rows = []
    for group, panels in groups:
        for panel_title, metrics, _ in panels:
            for metric in metrics:
                if metric not in day.columns:
                    continue
                info = meta[metric]
                series = day[metric].dropna()
                row = {'group': group, 'panel': panel_title.split(' — ')[0],
                       'metric': info['leaf'], 'where': info['location'],
                       'unit': info['unit'], 'n': len(series)}
                if series.empty or info['kind'] == 'circular':
                    # Direction has no meaningful min/max: 0º and 359º are 1º apart.
                    row |= {'min': None, 'mean': None, 'max': None, 'last': None}
                else:
                    row |= {
                        'min': round(series.min(), 2),
                        # A mean of a running total is meaningless; `last` is
                        # the number that matters for an accumulator.
                        'mean': (None if info['kind'] == 'accumulator'
                                 else round(series.mean(), 2)),
                        'max': round(series.max(), 2),
                        'last': round(series.iloc[-1], 2)}
                rows.append(row)
    return pd.DataFrame(rows)


def report_title(start):
    return f'{start:%A %d %B %Y} · {DISPLAY_TZ}'


# --------------------------------------------------------------------------
# Rolling view: the same checks across the last N days
# --------------------------------------------------------------------------

VERDICT_FILL = {
    # Light tints, not saturated blocks: these have to stay readable in
    # greyscale on a laser printer, and a wall of solid red reads as panic
    # rather than information.
    'PASS': 'background-color: #e2f0ec; color: #123a33',
    'WARN': 'background-color: #f9efd8; color: #4a3210',
    'FAIL': 'background-color: #f7e4de; color: #5e2716',
}


def rolling_checks(conn, meta, fetch_window, end, days=7):
    """Run every check once per day over a rolling window.

    One query, not `days` queries: the whole span is fetched at 5-minute
    resolution and sliced per local calendar day. Slicing on the local naive
    index is also what keeps a DST day the right length.

    Returns (pivot, measured, notes):
      pivot     check x day  -> verdict
      measured  check        -> the most recent day's measured value
      notes     check        -> why the check exists (for the hover text)
    """
    start = end - timedelta(days=days)
    span = fetch_window(conn, start, end, bucket='5 minutes', freq='5min')

    columns, measured, notes = {}, {}, {}
    for offset in range(days, 0, -1):
        day_start = end - timedelta(days=offset)
        day_end = day_start + timedelta(days=1)
        day = span.loc[(span.index >= day_start.replace(tzinfo=None))
                       & (span.index < day_end.replace(tzinfo=None))]
        if day.empty:
            continue
        frame = run_checks(conn, day, meta, day_start, day_end)
        columns[f'{day_start:%a %d}'] = frame.set_index('check').verdict
        measured = frame.set_index('check').measured      # last one wins = most recent
        notes = frame.set_index('check').note

    pivot = pd.DataFrame(columns)
    return pivot, measured, notes


def style_rolling(pivot, measured, notes):
    """Check | Measured | one colour-coded column per day, notes on hover.

    Column order is the ask: what was checked, what it measured most recently,
    then the trend. A single day says whether today is broken; the row of days
    says whether it has been drifting.
    """
    table = pd.concat([measured.rename('Measured'), pivot], axis=1)
    table.index.name = 'Check'

    # Tooltips carry the "why" without spending a column on it.
    tips = pd.DataFrame('', index=table.index, columns=table.columns)
    tips['Measured'] = notes.reindex(table.index).fillna('')

    styler = (table.style
              .map(lambda v: VERDICT_FILL.get(v, ''), subset=pivot.columns)
              .set_tooltips(tips)
              .set_properties(**{'text-align': 'center'}, subset=pivot.columns)
              .set_table_styles([
                  {'selector': 'th', 'props': [('text-align', 'left')]},
                  {'selector': 'td', 'props': [('padding', '3px 8px')]}]))
    return styler


def rolling_banner(pivot):
    """One line about the whole window, not just the newest day."""
    if pivot.empty:
        return 'no days with data in the window'
    fails = (pivot == 'FAIL').sum().sum()
    warns = (pivot == 'WARN').sum().sum()
    clean_days = int((pivot != 'FAIL').all().sum())
    return (f'{clean_days} of {pivot.shape[1]} days free of failures · '
            f'{fails} failure(s), {warns} warning(s) across the window')


def attention(pivot, measured, notes):
    """What a daily email keys off: severity, a headline, and what to look at.

    Kept separate from the styling so the future email and the notebook agree
    on what "needs attention" means rather than each deciding for itself.
    """
    if pivot.empty:
        return {'severity': 'alert', 'headline': 'no data for the window',
                'items': []}
    latest = pivot.columns[-1]
    today = pivot[latest]
    fails = list(today[today == 'FAIL'].index)
    warns = list(today[today == 'WARN'].index)

    # A check that failed earlier in the window and has not failed since is
    # still worth naming -- it is the difference between "fixed" and "ignored".
    earlier = [c for c in pivot.index
               if (pivot.loc[c] == 'FAIL').any() and c not in fails]

    # How many days this check has been bad WITHOUT a break, counting back from
    # the newest day. An unresolved failure is still news each morning -- six
    # days of failure should send six emails -- but an alert that reads
    # identically on day 6 and day 1 trains people to skim it. This is what lets
    # the body say "day 6 of this".
    def run_length(check):
        row = pivot.loc[check]
        days = 0
        for verdict in reversed(list(row)):
            if verdict not in ('FAIL', 'WARN'):
                break
            days += 1
        return days

    if fails:
        severity = 'alert'
        headline = f'{len(fails)} check(s) failed on {latest}: ' + '; '.join(fails)
    elif warns:
        severity = 'warn'
        headline = f'{len(warns)} warning(s) on {latest}: ' + '; '.join(warns)
    else:
        severity = 'ok'
        headline = f'all checks passed on {latest}'
    return {'severity': severity, 'headline': headline,
            'items': [{'check': c, 'measured': measured.get(c, ''),
                       'note': notes.get(c, ''), 'verdict': pivot.loc[c].iloc[-1],
                       'days': run_length(c)} for c in fails + warns],
            'resolved_earlier': earlier,
            # The window the run length was measured over: "day 7 of this" out of
            # a 7-day pivot may well mean "day 7 or more", and the email should
            # not claim precision the window cannot support.
            'window_days': pivot.shape[1]}
