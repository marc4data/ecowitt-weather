"""Normalisation tests, driven by the recorded Phase 0 captures.

§10: "Tests use recorded fixtures, never the live API." These read the real
24-hour history capture from samples/raw/ when it is present, and fall back to
synthetic payloads so the suite still runs on a clean checkout.
"""

from __future__ import annotations

import glob
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ingest.normalize import (
    Observation,
    duplicate_keys,
    median_delta,
    normalize_history,
)

STATION = "AA:BB:CC:DD:EE:FF"
NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)


def _history(series: dict[str, str], unit: str = "ºF") -> dict:
    return {
        "code": 0,
        "msg": "success",
        "data": {"outdoor": {"temperature": {"unit": unit, "list": series}}},
    }


def test_epochs_become_utc_aware_datetimes():
    result = normalize_history(_history({"1785644149": "78.3"}), station_id=STATION, now=NOW)
    obs = result.observations[0]
    assert obs.ts_utc == datetime(2026, 8, 2, 4, 15, 49, tzinfo=timezone.utc)
    assert obs.ts_utc.tzinfo is not None, "naive datetimes break across DST (CLAUDE.md §5.3)"


def test_exact_unit_bytes_are_preserved():
    """ºF is U+00BA. Normalising it to U+00B0 would silently rewrite history."""
    result = normalize_history(_history({"1785644149": "78.3"}), station_id=STATION, now=NOW)
    unit = result.observations[0].unit
    assert unit == "ºF"
    assert ord(unit[0]) == 0x00BA, "unit was normalised away from MASCULINE ORDINAL INDICATOR"


def test_unparseable_value_is_recorded_not_raised():
    """No unconditional casts: value_text keeps the bytes, value_num is None."""
    result = normalize_history(_history({"1785644149": "n/a"}), station_id=STATION, now=NOW)
    obs = result.observations[0]
    assert obs.value_text == "n/a"
    assert obs.value_num is None


def test_empty_value_is_quarantined_not_stored():
    result = normalize_history(_history({"1785644149": ""}), station_id=STATION, now=NOW)
    assert not result.observations
    assert "empty value" in result.rejections[0].reason


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_nan_and_infinity_do_not_become_numbers(value):
    """float() accepts these; a database column should not."""
    result = normalize_history(_history({"1785644149": value}), station_id=STATION, now=NOW)
    assert result.observations[0].value_num is None
    assert result.observations[0].value_text == value


def test_future_timestamp_is_quarantined():
    future = int((NOW + timedelta(days=1)).timestamp())
    result = normalize_history(_history({str(future): "78.3"}), station_id=STATION, now=NOW)
    assert not result.observations
    assert "future" in result.rejections[0].reason


def test_implausibly_old_timestamp_is_quarantined():
    result = normalize_history(_history({"946684800": "78.3"}), station_id=STATION, now=NOW)
    assert not result.observations
    assert "implausibly old" in result.rejections[0].reason


def test_unparseable_epoch_is_quarantined():
    result = normalize_history(_history({"not-an-epoch": "78.3"}), station_id=STATION, now=NOW)
    assert not result.observations
    assert "unparseable epoch" in result.rejections[0].reason


def test_nothing_is_ever_silently_dropped():
    """Every input becomes an observation or a rejection. §10."""
    payload = _history(
        {
            "1785644149": "78.3",  # good
            "1785644449": "",  # empty
            "bad": "1.0",  # bad epoch
            "946684800": "5",  # too old
        }
    )
    result = normalize_history(payload, station_id=STATION, now=NOW)
    assert result.fetched == 4


def test_median_delta_detects_a_30min_grid():
    """The silent-downgrade detector. 1800s must not read as 300s."""
    base = 1785644100
    assert median_delta([base + n * 300 for n in range(10)]) == 300
    assert median_delta([base + n * 1800 for n in range(10)]) == 1800
    assert median_delta([base]) is None


def test_median_delta_tolerates_a_gap():
    """Gaps are routine here; one dropout must not skew the median."""
    base = 1785644100
    stamps = [base + n * 300 for n in range(20)]
    del stamps[10:14]  # a 20-minute hole
    assert median_delta(stamps) == 300


def test_duplicate_natural_keys_are_detected():
    ts = datetime(2026, 8, 2, 4, 15, tzinfo=timezone.utc)
    rows = [
        Observation(STATION, ts, "outdoor.temperature", "78.3", 78.3, "ºF"),
        Observation(STATION, ts, "outdoor.temperature", "78.4", 78.4, "ºF"),
        Observation(STATION, ts, "outdoor.humidity", "62", 62.0, "%"),
    ]
    assert len(duplicate_keys(rows)) == 1


def test_missing_unit_is_rejected_not_defaulted():
    payload = {"data": {"outdoor": {"temperature": {"list": {"1785644149": "78.3"}}}}}
    result = normalize_history(payload, station_id=STATION, now=NOW)
    assert not result.observations
    assert "missing unit" in result.rejections[0].reason


def test_empty_payload_yields_nothing_without_crashing():
    for payload in ({}, {"code": 0}, {"code": 0, "data": {}}, {"data": None}):
        result = normalize_history(payload, station_id=STATION, now=NOW)
        assert result.fetched == 0


# --- against the real recorded capture --------------------------------------


def _recorded_history() -> dict | None:
    root = Path(__file__).resolve().parent.parent
    matches = [
        p
        for p in glob.glob(str(root / "samples/raw/device-history_d3-history-24h_*.json"))
        if not p.endswith(".meta.json")
    ]
    return json.loads(Path(matches[0]).read_text(encoding="utf-8")) if matches else None


@pytest.mark.skipif(_recorded_history() is None, reason="no recorded capture on disk")
def test_real_capture_normalises_to_the_expected_shape():
    payload = _recorded_history()
    result = normalize_history(payload, station_id=STATION, now=datetime.now(timezone.utc))

    assert result.observed_delta_s == 300, "recorded capture is a 5-minute grid"
    assert result.point_count == 281, "281 of 289 expected points — two real dropouts"
    assert len(result.groups_seen) == 12
    assert not result.rejections, "the real capture should normalise cleanly"

    metrics = {o.metric for o in result.observations}
    assert "outdoor.vpd" in metrics, "field absent from the published docs"
    assert "rainfall_piezo.1_hour" in metrics, "wire name, not the documented 'hourly'"
    assert len(metrics) == 39, "history exposes 39 leaves; real-time has 42"

    units = {o.unit for o in result.observations if o.metric.endswith("temperature")}
    assert units == {"ºF"}
