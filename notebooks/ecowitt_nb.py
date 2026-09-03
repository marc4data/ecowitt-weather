"""Shared plumbing for the Ecowitt notebooks.

    explore.ipynb        schema exploration -- what is in the database, and what
                         shape is it
    explore_daily.ipynb  the daily report -- boundary conditions, summary,
                         supporting detail
    audit.ipynb          all-time integrity (independent; does not use this)

Everything the first two both need lives here, so a fix lands in one place. That
is not hypothetical tidiness: the tunnel-ownership bug had to be fixed twice
because the same cell had been copied between two notebooks.

The kernel/dependency preflight deliberately stays IN each notebook. It repairs
`sys.path` before any third-party import -- including this module's own -- so it
cannot live behind an import.

Nothing here connects, queries, or draws at import time. Call `ensure_db()`.
"""

from __future__ import annotations

import atexit
import contextlib
import os
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

# The console reports in local time and the database stores UTC. Day boundaries
# are a human idea, so they are computed in console-local time; only display is
# shifted, never storage.
DISPLAY_TZ = ZoneInfo('America/Chicago')

TUNNEL_HOST, TUNNEL_PORT = '127.0.0.1', 5433
TUNNEL_LOG = Path(tempfile.gettempdir()) / 'ecowitt-tunnel.log'

DB_NAME, DB_USER = 'ecowitt', 'ecowitt_ro'
DB_SECRET = 'ecowitt-readonly-password'

# Categorical palette, in slot order. The order is the colourblind-safety
# mechanism, not decoration: consecutive slots were checked to stay apart under
# protanopia/deuteranopia/tritanopia simulation, so taking slots 1..n in order
# is safe and re-ordering them is not.
SERIES_COLORS = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100',
                 '#e87ba4', '#008300', '#4a3aa7', '#e34948']
SURFACE, GRID, AXIS, INK, MUTED = '#fcfcfb', '#e1e0d9', '#c3c2b7', '#0b0b0b', '#898781'

_tunnel_proc = None      # set only when THIS process started the tunnel
_engine = None
_conn = None


# --------------------------------------------------------------------------
# Tunnel
#
# WHY ONE EXISTS AT ALL -- this cannot be automated away. Postgres on the VM
# binds to localhost only and the VM accepts no inbound connections; even SSH
# arrives through an IAP tunnel. So any client on this machine needs a
# forwarded local port. The tunnel IS the access path, not a workaround.
#
# What was never necessary is a human opening it in a second terminal.
# --------------------------------------------------------------------------

def _repo_root():
    for base in (Path.cwd(), *Path.cwd().parents):
        if (base / 'infra' / 'tunnel.sh').is_file():
            return base
    return None


def tunnel_up(timeout=1.0):
    """Can something actually be connected to on the port?

    A connect() rather than a check for a listening process, deliberately:
    'a process is listening' and 'a query will work' are different claims.
    """
    with socket.socket() as probe:
        probe.settimeout(timeout)
        return probe.connect_ex((TUNNEL_HOST, TUNNEL_PORT)) == 0


def _foreign_clients():
    """Other processes with a live connection through the tunnel.

    A tunnel is shared infrastructure, not something the kernel that happened
    to start it owns -- two notebooks open at once is the normal case. Returns
    None when lsof cannot answer, which the caller treats as "unknown".
    """
    if shutil.which('lsof') is None:
        return None
    try:
        out = subprocess.run(
            ['lsof', '-nP', f'-iTCP:{TUNNEL_PORT}', '-sTCP:ESTABLISHED', '-Fp'],
            capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None

    # The tunnel's own ssh is the server side of every loopback connection, so
    # it must not count as a user of itself.
    tunnel_pgid = None
    if _tunnel_proc and _tunnel_proc.poll() is None:
        with contextlib.suppress(OSError):
            tunnel_pgid = os.getpgid(_tunnel_proc.pid)

    others = set()
    for line in out.splitlines():
        if not line.startswith('p'):
            continue
        pid = int(line[1:])
        if pid == os.getpid():
            continue
        try:
            if tunnel_pgid is not None and os.getpgid(pid) == tunnel_pgid:
                continue
        except OSError:
            continue
        others.add(pid)
    return others


def close_tunnel(force=False):
    """Close the tunnel this process opened -- unless someone else is on it.

    Without the check, shutting down this kernel yanks the tunnel out from
    under any other notebook using it. Leaving it open is the safe direction: a
    stray tunnel costs nothing and `ensure_tunnel` reuses it, whereas killing a
    live one breaks the other session mid-query.
    """
    global _tunnel_proc
    if not (_tunnel_proc and _tunnel_proc.poll() is None):
        return
    others = _foreign_clients()
    if others and not force:
        print(f'leaving the tunnel open — still in use by pid(s) {sorted(others)}')
        return
    os.killpg(os.getpgid(_tunnel_proc.pid), signal.SIGTERM)
    _tunnel_proc = None


def ensure_tunnel(wait_s=90, verbose=True):
    """Return once localhost:5433 accepts connections, starting one if needed."""
    global _tunnel_proc
    if tunnel_up():
        return 'tunnel already up'

    root = _repo_root()
    if root is None:
        raise SystemExit(
            f'Nothing listening on {TUNNEL_HOST}:{TUNNEL_PORT}, and infra/tunnel.sh was\n'
            f'not found above {Path.cwd()}. Open one by hand: ./infra/tunnel.sh')

    if verbose:
        print(f'no tunnel on {TUNNEL_HOST}:{TUNNEL_PORT} — starting one ...')
    # start_new_session puts it in its own process group, so interrupting a
    # cell does not kill the tunnel. That also means nothing reaps it for us,
    # hence close_tunnel + atexit.
    _tunnel_proc = subprocess.Popen(
        ['bash', str(root / 'infra' / 'tunnel.sh')],
        stdout=TUNNEL_LOG.open('w'), stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, start_new_session=True, cwd=root)
    atexit.register(close_tunnel)

    deadline = time.time() + wait_s
    while time.time() < deadline:
        if tunnel_up():
            if verbose:
                print(f'tunnel up on {TUNNEL_HOST}:{TUNNEL_PORT}  (log: {TUNNEL_LOG})')
            return 'tunnel opened'
        # tunnel.sh exits non-zero for the cases actually worth reading: run on
        # the VM, gcloud authenticated as a service account, or the port
        # already owned by a tunnel it cannot manage. Surface its own words.
        if (rc := _tunnel_proc.poll()) is not None:
            raise SystemExit(
                f'infra/tunnel.sh exited with code {rc} before the port came up.\n\n'
                f'{TUNNEL_LOG.read_text()[-1500:]}')
        time.sleep(1)

    close_tunnel()
    raise SystemExit(f'tunnel did not come up within {wait_s}s. Log: {TUNNEL_LOG}')


# --------------------------------------------------------------------------
# Connection
# --------------------------------------------------------------------------

def password():
    """Env var first, else Secret Manager. Never stored in a notebook."""
    if pw := os.environ.get('ECOWITT_RO_PASSWORD'):
        return pw
    # The timeout matters more than it looks. capture_output swallows anything
    # gcloud prints, so if it decides to prompt -- expired credentials, a
    # confirmation -- it blocks forever on a question nobody can see, and the
    # cell just sits there. Failing loudly after a minute beats hanging.
    try:
        out = subprocess.run(
            ['gcloud', 'secrets', 'versions', 'access', 'latest', f'--secret={DB_SECRET}'],
            capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f'gcloud did not return within 60s reading {DB_SECRET}. It is probably '
            'waiting on a prompt you cannot see. Run this in a terminal to find out:\n'
            f'    gcloud secrets versions access latest --secret={DB_SECRET}\n'
            'Or set ECOWITT_RO_PASSWORD to skip Secret Manager entirely.') from None
    if out.returncode != 0:
        raise RuntimeError(f'could not read {DB_SECRET}: {out.stderr.strip()[:200]}')
    return out.stdout.strip()


def engine():
    global _engine
    if _engine is None:
        _engine = create_engine(
            f'postgresql+psycopg://{DB_USER}:{quote_plus(password())}'
            f'@{TUNNEL_HOST}:{TUNNEL_PORT}/{DB_NAME}',
            connect_args={'connect_timeout': 10})
    return _engine


def ensure_db():
    """A live read-only connection, opening the tunnel first if needed.

    The liveness probe is not paranoia. A tunnel can die underneath an open
    connection -- the IAP websocket drops and ssh exits -- and SQLAlchemy still
    reports `closed` as False, because as far as it knows nobody closed
    anything. Only a query finds out, and by then the whole pool is poisoned.
    """
    global _conn
    ensure_tunnel()
    if _conn is not None and not _conn.closed:
        try:
            _conn.execute(text('SELECT 1'))
            return _conn
        except Exception:
            print('connection was stale (tunnel dropped?) — reconnecting')
            with contextlib.suppress(Exception):
                _conn.close()
            engine().dispose()
    _conn = engine().connect()
    return _conn


def shutdown():
    """Close the connection. The tunnel is left to close_tunnel's own rules."""
    global _conn
    if _conn is not None and not _conn.closed:
        _conn.close()
    _conn = None
    if _engine is not None:
        _engine.dispose()
    print('connection closed')


# --------------------------------------------------------------------------
# Charts
# --------------------------------------------------------------------------

def style():
    """Light surface, hairline grid, thin lines -- these print legibly on a
    mono laser printer, which a dark theme does not."""
    plt.rcParams.update({
        'figure.facecolor': SURFACE, 'axes.facecolor': SURFACE,
        'axes.edgecolor': AXIS, 'axes.labelcolor': INK, 'text.color': INK,
        'xtick.color': MUTED, 'ytick.color': MUTED,
        'grid.color': GRID, 'grid.linewidth': 0.8, 'grid.linestyle': '-',
        'axes.grid': True, 'axes.grid.axis': 'y',
        'axes.spines.top': False, 'axes.spines.right': False,
        'lines.linewidth': 1.8, 'font.size': 9, 'figure.dpi': 110,
    })


def show():
    """Render pending figures. Wrapped so notebooks need no pyplot import."""
    plt.show()


def break_wraps(series, threshold=180.0):
    """Split a circular series where it crosses north.

    A line drawn from 359 deg to 1 deg sweeps down through every angle in
    between -- a wind that never blew. Blanking the point after each wrap
    breaks the line instead; the blanked points come back as dots, so no
    observation is hidden.
    """
    jump = series.diff().abs() > threshold
    return series.mask(jump), series[jump]


# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------

# Each metric is aggregated by its own metric_catalog.resample_rule, because one
# rule cannot serve every metric: a mean of a wind direction can point due south
# for a north wind, a mean of a gust understates the peak, and a mean of a
# running total means nothing at all.
BUCKET_SQL = '''
WITH bounded AS (
    SELECT date_bin(CAST(:bucket AS interval), o.ts_utc,
                    CAST(:origin AS timestamptz)) AS bucket_utc,
           o.ts_utc, o.metric, o.value_num, c.resample_rule
      FROM observation o
      JOIN metric_catalog c USING (metric)
     WHERE o.ts_utc >= :start AND o.ts_utc < :end
       AND o.value_num IS NOT NULL
),
agg AS (
    SELECT bucket_utc, metric, resample_rule,
           avg(value_num)                                     AS v_mean,
           max(value_num)                                     AS v_max,
           (array_agg(value_num ORDER BY ts_utc DESC))[1]     AS v_last,
           atan2d(avg(sind(value_num)), avg(cosd(value_num))) AS v_vector
      FROM bounded
     GROUP BY 1, 2, 3
)
SELECT bucket_utc, metric,
       CASE resample_rule
           WHEN 'max'         THEN v_max
           WHEN 'last'        THEN v_last
           WHEN 'carry'       THEN v_last
           WHEN 'vector_mean' THEN CASE WHEN v_vector < 0 THEN v_vector + 360 ELSE v_vector END
           ELSE v_mean
       END AS value
  FROM agg
 ORDER BY bucket_utc, metric
'''


def fetch_window(conn, start, end, bucket, freq):
    """Bucketed metrics for a window, pivoted wide on a complete time grid.

    The reindex is the important part. Without it a dropout is drawn as a
    straight segment between the observations either side -- a line through
    values the station never reported. Reindexing turns it into NaN, and
    matplotlib leaves a visible break.

    `start`/`end` must be timezone-aware. The grid is generated from them in
    their own zone, which is what makes a DST day come out as 23 or 25 hours
    rather than a wrong 24.
    """
    long = pd.read_sql(text(BUCKET_SQL), conn, params={
        'bucket': bucket, 'origin': start, 'start': start, 'end': end})
    wide = long.pivot(index='bucket_utc', columns='metric', values='value')
    grid = pd.date_range(start, end, freq=freq, inclusive='left')
    wide = wide.reindex(grid.tz_convert('UTC'))
    # Convert for display, then drop the offset: the zone is stated in the
    # titles, and matplotlib's date locators are simpler on naive stamps.
    wide.index = wide.index.tz_convert(DISPLAY_TZ).tz_localize(None)
    return wide


def yesterday_bounds(tz=DISPLAY_TZ):
    """Yesterday as a complete local calendar day.

    Built from local midnight rather than `now - 24h`: on a DST changeover the
    two differ by an hour, and it is the calendar day that people mean.
    """
    midnight = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight - timedelta(days=1), midnight


# --------------------------------------------------------------------------
# Metric metadata
# --------------------------------------------------------------------------

def split_metric(metric):
    """'temp_and_humidity_ch1.temperature' -> ('temp_and_humidity','ch1','temperature')

    The channel suffix sits on the group for the temp/humidity and soil sensors
    but on the leaf for their battery entries, so both places are checked.
    """
    import re
    channel = re.compile(r'_(ch\d+)$')
    group, _, leaf = metric.partition('.')
    if m := channel.search(group):
        return group[:m.start()], m.group(1), leaf
    if m := channel.search(leaf):
        return group, m.group(1), leaf[:m.start()]
    return group, None, leaf


# What the paired channels actually are, confirmed 2026-08-28. Mapped here, in
# `location`, rather than in each consumer: the checks, the chart legends, the
# detail table and the daily email all read that one field, so a room named once
# is a room named everywhere. The raw `channel` is left untouched, because it is
# what the API and the metric names use and it is what a query has to match.
#
# The two soil probes are still unidentified and are deliberately absent -- an
# unmapped channel keeps its own label, and a wrong room name is worse than a
# channel number.
ROOM_NAMES = {
    'ch1': 'Basement',
    'ch2': 'Living Room',
    'ch3': 'Office/Bedroom',
}


def load_meta(conn):
    """Every metric's realm, channel, leaf, location, unit, kind and rule."""
    catalog = pd.read_sql(text(
        'SELECT metric, kind, canonical_unit AS unit, resample_rule '
        'FROM metric_catalog'), conn).set_index('metric')
    meta = {}
    for metric in catalog.index:
        realm, channel, leaf = split_metric(metric)
        meta[metric] = dict(
            realm=realm, channel=channel, leaf=leaf,
            # 'outdoor', 'indoor', 'Living Room', ... — the soil channels stay
            # 'ch1'/'ch2' until somebody says what they are.
            location=ROOM_NAMES.get(channel, channel) or realm,
            unit=catalog.loc[metric, 'unit'] or '',
            kind=catalog.loc[metric, 'kind'],
            rule=catalog.loc[metric, 'resample_rule'])
    return meta


# Outdoor first, then indoor, then the numbered channels -- reading order for a
# weather station, rather than however the metric names happen to sort.
LOCATION_ORDER = ['outdoor', 'indoor']


def by_leaf(meta, leaf):
    """Every sensor reporting this measurement, e.g. all five thermometers."""
    def key(metric):
        loc = meta[metric]['location']
        return (LOCATION_ORDER.index(loc) if loc in LOCATION_ORDER
                else len(LOCATION_ORDER), loc)
    return sorted((m for m, v in meta.items() if v['leaf'] == leaf), key=key)


def by_realm(meta, realm, unit=None):
    return sorted(m for m, v in meta.items()
                  if v['realm'] == realm and (unit is None or v['unit'] == unit))


def logical_groups(meta, present=None):
    """Metrics grouped by the question being asked, not by the API's shape.

    Each panel is (title, metrics, what colour means). `present` is the set of
    metrics that actually have data; anything in it that no group claims comes
    back as a trailing "Not yet grouped" entry rather than disappearing --
    this list is hand-written, and a hand-written list goes stale the moment a
    sensor is added.
    """
    groups = [
        ('Temperature', [
            ('every thermometer', by_leaf(meta, 'temperature'), 'location'),
            ('outdoor — and how it felt',
             ['outdoor.temperature', 'outdoor.feels_like', 'outdoor.app_temp',
              'outdoor.dew_point'], 'metric'),
            ('indoor — and how it felt',
             ['indoor.temperature', 'indoor.feels_like', 'indoor.app_tempin',
              'indoor.dew_point'], 'metric'),
        ]),
        ('Humidity and air moisture', [
            ('relative humidity, every sensor', by_leaf(meta, 'humidity'), 'location'),
            ('vapour pressure deficit — how hard the air pulls water from things',
             ['outdoor.vpd'], 'metric'),
        ]),
        ('Wind', [
            ('speed and gust', ['wind.wind_speed', 'wind.wind_gust'], 'metric'),
            ('direction', ['wind.wind_direction'], 'metric'),
        ]),
        ('Rain', [
            ('accumulators — each resets on its own cycle',
             by_realm(meta, 'rainfall_piezo', unit='in'), 'metric'),
            ('rate', ['rainfall_piezo.rain_rate'], 'metric'),
        ]),
        ('Sun', [
            ('solar irradiance', ['solar_and_uvi.solar'], 'metric'),
            ('UV index', ['solar_and_uvi.uvi'], 'metric'),
        ]),
        ('Pressure', [
            ('station pressure', by_realm(meta, 'pressure'), 'metric'),
        ]),
        ('Soil', [
            ('moisture', by_leaf(meta, 'soilmoisture'), 'location'),
            ('raw ad — opaque, carried rather than averaged',
             by_leaf(meta, 'ad'), 'location'),
        ]),
        ('Sensor health', [
            ('battery voltage', by_realm(meta, 'battery', unit='V'), 'metric'),
        ]),
    ]
    if present is not None:
        claimed = {m for _, panels in groups for _, metrics, _ in panels for m in metrics}
        if orphans := sorted(set(present) - claimed):
            groups.append(('Not yet grouped', [('unassigned metrics', orphans, 'metric')]))
    return groups


def plot_group(frame, meta, title, panels, start, end, subtitle=''):
    """One figure per logical group: panels stacked on one shared time axis.

    Stacking on a shared axis is the point -- a vertical line through the
    figure is a single instant, so the cloud that cuts solar at 13:00 is
    visibly the same event that cuts UV index at 13:00.
    """
    live = [(t, [m for m in ms if m in frame.columns and frame[m].notna().any()], by)
            for t, ms, by in panels]
    live = [(t, ms, by) for t, ms, by in live if ms]
    if not live:
        return None

    fig, axes = plt.subplots(len(live), 1, figsize=(11, 2.3 * len(live) + 0.7),
                             sharex=True, squeeze=False, layout='constrained')
    # strict=True: one axis per live panel is guaranteed by the subplots call
    # above, so a mismatch would be a bug worth raising rather than truncating.
    for ax, (panel_title, metrics, color_by) in zip(axes[:, 0], live, strict=True):
        units = {meta[m]['unit'] for m in metrics}
        for slot, metric in enumerate(metrics):
            info = meta[metric]
            color = SERIES_COLORS[slot % len(SERIES_COLORS)]
            label = info['location'] if color_by == 'location' else info['leaf']
            if info['kind'] == 'circular':
                line, dots = break_wraps(frame[metric])
                ax.plot(line.index, line.values, color=color, label=label)
                ax.plot(dots.index, dots.values, '.', color=color, markersize=4)
            else:
                # Accumulators and carried values hold until the next reading,
                # so a step is what actually happened; a sloped line would
                # imply readings that were never taken.
                ax.plot(frame[metric].index, frame[metric].values, color=color, label=label,
                        drawstyle='steps-post' if info['rule'] in ('last', 'carry') else 'default')

        # Panels are built from one unit by construction; if that ever stops
        # being true, say so on the axis rather than mislabelling it.
        unit = units.pop() if len(units) == 1 else 'MIXED UNITS'
        ax.set_ylabel(unit or 'unitless')
        ax.set_title(panel_title, fontsize=9.5, color=INK, loc='left')
        # One series needs no legend -- the panel title already names it.
        if len(metrics) > 1:
            ax.legend(loc='upper left', bbox_to_anchor=(1.01, 1.0),
                      frameon=False, fontsize=8.5, handlelength=1.4)
        if unit == 'º':
            ax.set_ylim(-10, 370)
            ax.set_yticks([0, 90, 180, 270, 360])

    # Fix the x-axis to the whole window on every figure, so a sensor that
    # reported for only part of it is visibly partial rather than rescaled.
    bottom = axes[-1, 0]
    bottom.set_xlim(start.replace(tzinfo=None), end.replace(tzinfo=None))
    bottom.xaxis.set_major_locator(mdates.HourLocator(interval=3))
    bottom.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    fig.suptitle(f'{title}{subtitle}', fontsize=12, ha='left', x=0.01)
    return fig


# --------------------------------------------------------------------------
# Multi-period trend grid (rows = scale bands, columns = periods)
# --------------------------------------------------------------------------

# Bucket width per period, chosen to land near ~100-170 points per chart:
# dense enough to show shape, sparse enough to stay readable.
PERIODS = {
    '24 hours': dict(days=1,  bucket='15 minutes', freq='15min'),
    '7 days':   dict(days=7,  bucket='1 hour',     freq='1h'),
    '30 days':  dict(days=30, bucket='6 hours',    freq='6h'),
}

# Rows run headline-measurement first, so temperature is at the top of the
# figure rather than wherever its unit string happens to sort.
UNIT_RANK = {'ºF': 0, '%': 1, 'mph': 2, 'W/m²': 3, 'inHg': 4,
             'in': 5, 'in/hr': 6, 'V': 7, 'º': 8}

# Within a (realm, unit), start a new band when the next metric is more than
# this much larger than the biggest so far.
SPLIT_RATIO = 10.0


def fetch_periods(conn, periods=None):
    """One wide frame per period, each on its own complete time grid."""
    periods = periods or PERIODS
    frames = {}
    for name, spec in periods.items():
        end = pd.Timestamp.now(tz=DISPLAY_TZ).ceil(spec['freq'])
        start = end - timedelta(days=spec['days'])
        frames[name] = fetch_window(conn, start, end,
                                    bucket=spec['bucket'], freq=spec['freq'])
    return frames


def build_plan(widest, meta):
    """Decide which metrics share a panel, and what colour each series gets.

    `widest` is the frame with the longest span -- magnitudes are judged there
    because it is the largest sample available. p95 rather than max, so one
    spike does not push a metric into a band of its own.
    """
    rows = []
    for metric in widest.columns:
        scale = widest[metric].abs().quantile(0.95)
        if pd.isna(scale) or metric not in meta:
            continue                      # all-NaN: the unitless status codes
        info = meta[metric]
        rows.append(dict(metric=metric, realm=info['realm'], channel=info['channel'],
                         leaf=info['leaf'], unit=info['unit'], kind=info['kind'],
                         rule=info['rule'], scale=float(scale)))
    plan = pd.DataFrame(rows)
    if plan.empty:
        return plan, {}, {}

    plan['band'] = 0
    for _, group in plan.groupby(['realm', 'unit'], sort=False):
        band, ceiling = 0, None
        for idx, scale in group.scale.sort_values().items():
            if ceiling and scale > 0 and scale / ceiling > SPLIT_RATIO:
                band, ceiling = band + 1, scale
            else:
                ceiling = max(ceiling or 0.0, scale) or None
            plan.loc[idx, 'band'] = band

    # `channel` is None for single-channel realms, which pandas stores as NaN --
    # and NaN is truthy, so a plain `if c` would label every series '· nan'.
    plan['label'] = plan.leaf + plan.channel.map(
        lambda c: f' · {c}' if isinstance(c, str) else '')
    plan['unit_rank'] = plan.unit.map(lambda u: UNIT_RANK.get(u, 99))

    def channel_keyed(realm_rows):
        """True when channel alone tells this realm's series apart in every band.

        True for temp_and_humidity and soil -- each band is one measurement read
        by several sensors. False for battery, where one band mixes different
        leaf metrics with and without channels.
        """
        if realm_rows.channel.isna().all():
            return False
        for _, band in realm_rows.groupby(['unit_rank', 'unit', 'band'], dropna=False):
            if band.leaf.nunique() != 1 or band.channel.isna().any():
                return False
        return True

    # Colour is assigned per REALM, so a series keeps its hue across all three
    # periods and every band, and one legend serves the whole figure. Where
    # channels are what distinguish the series, hue tracks the CHANNEL -- key it
    # on the metric instead and ch1 gets one colour in the temperature row and a
    # different one in the humidity row, which defeats colouring by provenance.
    colors, series_label, by_channel = {}, {}, {}
    for realm, group in plan.groupby('realm', sort=False):
        by_channel[realm] = channel_keyed(group)
        if by_channel[realm]:
            slots = {ch: SERIES_COLORS[i % len(SERIES_COLORS)]
                     for i, ch in enumerate(sorted(group.channel.dropna().unique()))}
            for row in group.itertuples():
                colors[row.metric] = slots[row.channel]
                series_label[row.metric] = row.channel
        else:
            for slot, row in enumerate(group.sort_values(['unit_rank', 'scale']).itertuples()):
                colors[row.metric] = SERIES_COLORS[slot % len(SERIES_COLORS)]
                series_label[row.metric] = row.label
    plan['series_label'] = plan.metric.map(series_label)
    plan.attrs['colors'] = colors
    plan.attrs['by_channel'] = by_channel
    return plan, colors, by_channel


def plot_realm(realm, plan, frames, colors, by_channel, periods=None, daylight=None):
    """One figure: rows are scale bands, columns are the periods."""
    periods = periods or PERIODS
    realm_plan = plan[plan.realm == realm].sort_values(['unit_rank', 'scale'])
    bands = realm_plan.groupby(['unit_rank', 'unit', 'band'], sort=True, dropna=False)
    keys = list(bands.groups)

    # sharey='row' is what makes the columns comparable: the 24-hour and 30-day
    # panels sit on one scale, so a flat week reads as flat rather than being
    # stretched to fill its own axis.
    fig, axes = plt.subplots(len(keys), len(periods),
                             figsize=(13, 2.6 * len(keys) + 0.9),
                             sharey='row', squeeze=False, layout='constrained')
    handles = {}
    for r, key in enumerate(keys):
        members = bands.get_group(key).sort_values('scale', ascending=False)
        unit = key[1]
        for c, period in enumerate(periods):
            ax, frame = axes[r][c], frames[period]
            drawn = False
            for member in members.itertuples():
                if member.metric not in frame.columns or frame[member.metric].isna().all():
                    continue
                drawn = True
                color = colors[member.metric]
                if member.kind == 'circular':
                    line, dots = break_wraps(frame[member.metric])
                    artist, = ax.plot(line.index, line.values, color=color)
                    ax.plot(dots.index, dots.values, '.', color=color, markersize=4)
                    degrees, consistency = resultant_direction(frame[member.metric])
                    if degrees is not None:
                        # The honest summary of a circular series: a vector
                        # mean, with the resultant length saying how much to
                        # trust it. A numeric mean would read 359 and 1 as 180.
                        ax.annotate(
                            f'mostly from {compass_point(degrees)}  ({consistency:.2f})',
                            xy=(0.02, 0.06), xycoords='axes fraction',
                            fontsize=8.5, color=MUTED)
                elif member.unit == 'mph':
                    # Wind is spiky enough that the raw trace hides its own
                    # shape. The 3-point mean carries the shape; the raw stays
                    # underneath at low weight so no peak is invented or lost.
                    ax.plot(frame[member.metric].index, frame[member.metric].values,
                            color=color, linewidth=0.7, alpha=0.30)
                    artist, = ax.plot(frame[member.metric].index,
                                      smooth(frame[member.metric]).values, color=color)
                else:
                    # Accumulators and carried values hold until the next
                    # reading, so a step is what actually happened; a sloped
                    # line would imply readings that were never taken.
                    artist, = ax.plot(
                        frame[member.metric].index, frame[member.metric].values, color=color,
                        drawstyle='steps-post' if member.rule in ('last', 'carry') else 'default')
                handles.setdefault(member.series_label, artist)

            if not drawn:
                ax.text(0.5, 0.5, 'no data in this window', transform=ax.transAxes,
                        ha='center', va='center', color=MUTED, fontsize=8)
                ax.set_xticks([])
            style_time_axis(ax, PERIOD_AXIS.get(period, 'month'),
                            daylight=daylight.get(period) if daylight else None)
            if r == 0:
                ax.set_title(f'last {period}', color=INK, fontsize=10)
            if c == 0:
                leaves = members.leaf.unique()
                shown = unit or 'unitless'
                # +2 over the base size: the y label is the only thing naming
                # what a row actually plots.
                ax.set_ylabel(f'{leaves[0]} ({shown})' if len(leaves) == 1 else shown,
                              fontsize=plt.rcParams['font.size'] + 2)
            if unit == 'º':
                # Degrees mean nothing at a glance; compass points do.
                ax.set_ylim(-10, 370)
                ax.set_yticks([0, 90, 180, 270, 360])
                ax.set_yticklabels(['N', 'E', 'S', 'W', 'N'])

    fig.suptitle(realm, fontsize=12, ha='left', x=0.01)
    ordered = list(dict.fromkeys(lbl for lbl in realm_plan.series_label if lbl in handles))
    if by_channel.get(realm):
        ordered.sort()
    fig.legend([handles[lbl] for lbl in ordered], ordered, loc='outside lower center',
               ncol=min(len(ordered), 6), frameon=False, fontsize=9)
    return fig


def period_summary(plan, frames, periods=None):
    """min/max per metric per period -- the table view for the trend grid."""
    periods = periods or PERIODS
    rows = []
    for row in plan.sort_values(['realm', 'unit_rank', 'band', 'scale']).itertuples():
        entry = {'realm': row.realm, 'metric': row.leaf,
                 'channel': row.channel if isinstance(row.channel, str) else '',
                 'unit': row.unit, 'rule': row.rule}
        for period in periods:
            series = frames[period].get(row.metric)
            series = series.dropna() if series is not None else pd.Series(dtype=float)
            entry[f'{period} n'] = len(series)
            # A circular metric has no meaningful min or max -- 0º and 359º are
            # one degree apart -- so only its coverage is reported.
            if series.empty or row.kind == 'circular':
                entry[f'{period} min'] = entry[f'{period} max'] = None
            else:
                entry[f'{period} min'] = round(series.min(), 2)
                entry[f'{period} max'] = round(series.max(), 2)
        rows.append(entry)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Time-axis styling
# --------------------------------------------------------------------------

# Which axis treatment each period gets. Keyed off the period name so a new
# period only needs an entry here.
PERIOD_AXIS = {'24 hours': 'day', '7 days': 'week', '30 days': 'month'}

NOON_RULE = '#9a988f'      # one step darker than the hairline grid
DAYLIGHT = '#f6efdc'       # pale sand; survives greyscale printing


def _compact_hour(value, _pos=None):
    """00:00 -> 12A, 15:00 -> 3P. Half the width of '15:00'."""
    hour = mdates.num2date(value).hour
    if hour == 0:
        return '12A'
    if hour < 12:
        return f'{hour}A'
    if hour == 12:
        return '12P'
    return f'{hour - 12}P'


def daylight_spans(solar, threshold=5.0):
    """Contiguous runs where the pyranometer sees light.

    Derived from the station's own solar reading rather than an astronomical
    sunrise/sunset for a stored lat/lon: it needs no coordinates, and it shades
    the daylight the sensor actually saw -- which is the thing the other series
    are being read against. A heavy overcast dawn genuinely starts later.
    """
    if solar is None or solar.dropna().empty:
        return []
    lit = solar.fillna(0) > threshold
    spans, start = [], None
    for stamp, is_lit in lit.items():
        if is_lit and start is None:
            start = stamp
        elif not is_lit and start is not None:
            spans.append((start, stamp))
            start = None
    if start is not None:
        spans.append((start, lit.index[-1]))
    return spans


def style_time_axis(ax, kind, daylight=None):
    """Ticks, gridlines and shading appropriate to the span being shown."""
    if kind == 'day':
        # byhour, not interval: interval anchors on whatever hour the window
        # happens to start, giving 2A/5A/8A. Clock multiples are what people read.
        ax.xaxis.set_major_locator(mdates.HourLocator(byhour=range(0, 24, 3)))
        ax.xaxis.set_major_formatter(mticker.FuncFormatter(_compact_hour))
        ax.grid(True, axis='x', color=GRID, linewidth=0.8)
        # Noon gets its own darker rule: on a 24-hour strip the eye needs one
        # fixed landmark to read the rest against.
        lo, hi = mdates.num2date(ax.get_xlim()[0]), mdates.num2date(ax.get_xlim()[1])
        for noon in pd.date_range(lo.date(), hi.date(), freq='D'):
            noon = noon + pd.Timedelta(hours=12)
            if lo.replace(tzinfo=None) <= noon <= hi.replace(tzinfo=None):
                ax.axvline(noon, color=NOON_RULE, linewidth=1.0, zorder=0.5)
        for start, end in (daylight or []):
            ax.axvspan(start, end, color=DAYLIGHT, zorder=0, linewidth=0)

    elif kind == 'week':
        # A tick and a rule on every day boundary -- seven days should read as
        # seven days, not as whatever tick count the autolocator settles on.
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%a %d'))
        ax.grid(True, axis='x', color=GRID, linewidth=0.8)

    else:
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=5))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
        ax.grid(True, axis='x', color=GRID, linewidth=0.8)


# --------------------------------------------------------------------------
# Wind
# --------------------------------------------------------------------------

COMPASS_16 = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
              'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']


def compass_point(degrees):
    return COMPASS_16[int((degrees % 360) / 22.5 + 0.5) % 16]


def resultant_direction(series):
    """Vector mean of a circular series: (degrees, consistency 0-1).

    The consistency is the resultant length. 1.0 means every reading pointed
    the same way; near 0 means the wind boxed the compass and the mean
    direction, however computed, means very little.

    This is why a numeric mean is never used: 359 deg and 1 deg average to 180
    -- due south for a wind that blew from the north.
    """
    values = series.dropna()
    if values.empty:
        return None, 0.0
    radians = np.deg2rad(values.to_numpy())
    east, north = np.sin(radians).mean(), np.cos(radians).mean()
    return float(np.rad2deg(np.arctan2(east, north)) % 360), float(np.hypot(east, north))


def smooth(series, window=3):
    """Centred rolling mean. Used on wind speed, which is spiky by nature."""
    return series.rolling(window, center=True, min_periods=1).mean()


def wind_rose(frames, periods=None, bins=16):
    """Where the wind came from, as frequency per compass sector.

    A rose rather than a line, because direction is circular: the line chart
    can only show it wrapping, never where it mostly sat.
    """
    periods = periods or PERIODS
    fig, axes = plt.subplots(1, len(periods), figsize=(4.2 * len(periods), 5.4),
                             subplot_kw={'projection': 'polar'}, layout='constrained')
    edges = np.deg2rad(np.arange(0, 361, 360 / bins) - (360 / bins) / 2)
    for ax, period in zip(np.atleast_1d(axes), periods, strict=True):
        series = frames[period].get('wind.wind_direction')
        ax.set_theta_zero_location('N')     # meteorological: 0 deg at the top
        ax.set_theta_direction(-1)          # and clockwise through E, S, W
        ax.set_xticks(np.deg2rad(np.arange(0, 360, 45)))
        ax.set_xticklabels(['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'], fontsize=9)
        ax.set_yticklabels([])
        ax.grid(color=GRID, linewidth=0.8)
        if series is None or series.dropna().empty:
            ax.set_title(f'last {period}\nno data', fontsize=10, color=MUTED)
            continue
        radians = np.deg2rad(series.dropna().to_numpy())
        counts, _ = np.histogram((radians + edges[0]) % (2 * np.pi) - edges[0], bins=edges)
        counts = np.asarray(counts, dtype=float)
        share = 100 * counts / counts.sum()
        centres = np.deg2rad(np.arange(0, 360, 360 / bins))
        ax.bar(centres, share, width=2 * np.pi / bins * 0.9,
               color=SERIES_COLORS[2], edgecolor=SURFACE, linewidth=1.0, zorder=2)
        degrees, consistency = resultant_direction(series)
        ax.set_title(f'last {period}\nfrom {compass_point(degrees)} ({degrees:.0f}º) · '
                     f'steadiness {consistency:.2f}', fontsize=10, color=INK)
    fig.suptitle('Where the wind came from — share of readings per sector',
                 fontsize=12, ha='left', x=0.01, y=1.02)
    return fig
