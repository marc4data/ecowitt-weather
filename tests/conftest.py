"""Fixtures for the reporting tests.

Recorded fixtures, never the live API and never the live database (§10). The
fixture database is SQLite because the four queries `run_checks` makes are plain
enough to run anywhere -- that is enough to exercise the real checks rather than
a stubbed copy of them, which is the whole point of testing here at all.

What SQLite CANNOT do is `fetch_window`: it leans on `date_bin`, `sind` and
`atan2d`. So the wide day frame is built directly in pandas, which is also how a
test gets to describe a day that never happened -- a house at 95 ºF, a dead
sensor, a 25-hour Sunday in November.
"""

from __future__ import annotations

import sys
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "notebooks"))

TZ = ZoneInfo("America/Chicago")

# A believable subset of the 42 metrics: enough for every check to have
# something to look at, few enough to write out by hand.
CATALOG = [
    ("outdoor.temperature", "instantaneous", "ºF", "mean"),
    ("outdoor.humidity", "instantaneous", "%", "mean"),
    ("outdoor.feels_like", "derived", "ºF", "recompute"),
    ("indoor.temperature", "instantaneous", "ºF", "mean"),
    ("indoor.humidity", "instantaneous", "%", "mean"),
    ("temp_and_humidity_ch1.temperature", "instantaneous", "ºF", "mean"),
    ("temp_and_humidity_ch1.humidity", "instantaneous", "%", "mean"),
    ("wind.wind_gust", "extremum", "mph", "max"),
    ("rainfall_piezo.daily", "accumulator", "in", "last"),
    ("rainfall_piezo.weekly", "accumulator", "in", "last"),
    # Catalogued `accumulator` like the two above, but really a trailing
    # 60-minute window -- R-002. It is in the fixture catalog precisely so a
    # test can tell the two apart.
    ("rainfall_piezo.1_hour", "accumulator", "in", "last"),
    ("solar_and_uvi.solar", "instantaneous", "W/m²", "mean"),
    ("battery.haptic_array_battery", "diagnostic", "V", "carry"),
    ("battery.haptic_array_capacitor", "diagnostic", "V", "carry"),
    ("battery.soilmoisture_sensor_ch1", "diagnostic", "V", "carry"),
]


def day_bounds(day: str):
    start = datetime.combine(pd.Timestamp(day).date(), time.min, tzinfo=TZ)
    end = datetime.combine(pd.Timestamp(day).date() + timedelta(days=1), time.min, tzinfo=TZ)
    return start, end


@pytest.fixture
def fixture_db():
    """An in-memory database with the tables the checks query, and nothing else."""
    engine = create_engine("sqlite://")
    conn = engine.connect()
    conn.execute(
        text("""
        CREATE TABLE metric_catalog (metric text primary key, kind text,
            canonical_unit text, resample_rule text)""")
    )
    conn.execute(text("CREATE TABLE run_log (status text, started_at timestamp)"))
    conn.execute(text("CREATE TABLE quarantine (ts_utc timestamp)"))
    conn.execute(text("CREATE TABLE change_log (ts_utc timestamp)"))
    conn.execute(
        text("""
        CREATE TABLE observation (ts_utc timestamp, metric text, value_num float)""")
    )
    for metric, kind, unit, rule in CATALOG:
        conn.execute(
            text("INSERT INTO metric_catalog VALUES (:m, :k, :u, :r)"),
            {"m": metric, "k": kind, "u": unit, "r": rule},
        )
    conn.commit()
    yield conn
    conn.close()


def seed_runs(conn, start, end, *, status: str = "succeeded", n: int = 24):
    for i in range(n):
        conn.execute(
            text("INSERT INTO run_log VALUES (:s, :t)"),
            {"s": status, "t": (start + timedelta(hours=i)).isoformat()},
        )
    conn.commit()


def seed_observations(conn, frame: pd.DataFrame):
    """Mirror the wide frame into `observation`, so liveness and the day-over-day
    comparison see the same world the frame describes."""
    # Localised as a whole index rather than stamp by stamp: on a fall-back day
    # 01:00-01:55 occurs twice, and a lone naive stamp from that hour is
    # genuinely ambiguous. `infer` resolves it from the order of the sequence,
    # which is the only thing that can.
    utc = frame.index.tz_localize(TZ, ambiguous="infer", nonexistent="shift_forward").tz_convert(
        "UTC"
    )
    # Positional, not by label: a fall-back day has duplicate naive stamps, and
    # looking one up by label returns both rows.
    for metric in frame.columns:
        for position, value in enumerate(frame[metric].to_numpy()):
            if pd.isna(value):
                continue
            conn.execute(
                text("INSERT INTO observation VALUES (:t, :m, :v)"),
                {"t": utc[position].isoformat(), "m": metric, "v": float(value)},
            )
    conn.commit()


def build_day(
    start,
    end,
    *,
    indoor=None,
    indoor_room=74.0,
    outdoor=(72.0, 95.0),
    battery_ch1=1.60,
    gaps: int = 0,
    empty: bool = False,
) -> pd.DataFrame:
    """A wide 5-minute frame for one local day.

    `indoor` may be a constant or a callable of the hour, which is how a test
    describes a house that is already hot versus one that is heating up -- the
    distinction the whole protection-band check exists to draw.
    """
    grid = pd.date_range(start, end, freq="5min", inclusive="left", tz=TZ)
    index = grid.tz_localize(None)
    if empty:
        return pd.DataFrame(index=index, columns=[m for m, *_ in CATALOG], dtype=float)

    hours = (index.hour + index.minute / 60.0).to_numpy(dtype=float)
    warm = outdoor[0] + (outdoor[1] - outdoor[0]) * (1 - abs(hours - 15) / 15).clip(0, 1)
    # A working A/C sawtooths as the compressor cycles, so the healthy fixture
    # behaves like a cooled house rather than holding one value.
    if indoor is None:
        inside = pd.Series(75.0 + 0.6 * ((hours * 2) % 2 - 0.5), index=index, dtype=float)
    else:
        inside = pd.Series(
            [indoor(h) for h in hours] if callable(indoor) else indoor, index=index, dtype=float
        )

    frame = pd.DataFrame(
        {
            "outdoor.temperature": warm,
            "outdoor.humidity": (100 - warm * 0.5).clip(10, 100),
            "outdoor.feels_like": warm + 4,
            "indoor.temperature": inside.values,
            "indoor.humidity": 45.0 + (hours % 3),
            "temp_and_humidity_ch1.temperature": (
                [indoor_room(h) for h in hours]
                if callable(indoor_room)
                else indoor_room + 0.4 * ((hours * 3) % 2 - 0.5)
            ),
            "temp_and_humidity_ch1.humidity": 46.0 + (hours % 2),
            "wind.wind_gust": (warm % 7) + 1,
            "rainfall_piezo.daily": 0.0,
            "rainfall_piezo.weekly": 0.0,
            "rainfall_piezo.1_hour": 0.0,
            "solar_and_uvi.solar": (1 - abs(hours - 13) / 7).clip(0, 1) * 900,
            "battery.haptic_array_battery": 3.28,
            # Charges through the day and drains overnight, like the real one.
            "battery.haptic_array_capacitor": 3.9 + (1 - abs(hours - 14) / 10).clip(0, 1) * 1.4,
            "battery.soilmoisture_sensor_ch1": battery_ch1,
        },
        index=index,
    )

    if gaps:
        frame.iloc[10 : 10 + gaps] = pd.NA
    return frame


@pytest.fixture(autouse=True)
def _isolate_report_env(monkeypatch):
    """Unset every report variable before each test.

    Without this, a test asserting "no contact is configured" passes on a clean
    shell and fails on the maintainer's, because LAKEHOUSE_CONTACTS happens to
    be exported. A test that depends on the ambient environment is a test that
    reports on the environment.
    """
    for name in (
        "LAKEHOUSE_CONTACTS",
        "LAKEHOUSE_EMAIL_TO",
        "LAKEHOUSE_EMAIL_TEST_TO",
        "LAKEHOUSE_EMAIL_FROM",
        "LAKEHOUSE_SMTP_USER",
        "LAKEHOUSE_SMTP_PASSWORD",
        "LAKEHOUSE_REPLY_TO",
        "LAKEHOUSE_STATION_URL",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_WORKSPACE_ID",
    ):
        monkeypatch.delenv(name, raising=False)
