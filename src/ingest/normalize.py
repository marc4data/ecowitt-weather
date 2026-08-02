"""Turn a raw API payload into observation rows, or into quarantine rows.

Deliberately pure: no database, no network, no clock beyond what is passed in.
That is what makes it testable against the recorded Phase 0 captures rather
than against the live API (§10), and it is why parsing bugs stay recoverable —
the raw payload is landed before any of this runs.

The two rules this module exists to honour:

* **No unconditional casts.** A value that will not parse is recorded as a
  parse failure, not raised as an exception and not silently turned into NULL.
  `value_text` always holds the exact bytes; `value_num` is None when the cast
  fails, and the two together keep the distinction between "sensor reported
  something unparseable" and "sensor reported nothing".
* **Rejected rows are quarantined, not dropped.** Every input either becomes an
  observation or becomes a quarantine row with a reason. Nothing disappears.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

# A timestamp outside this band is not a clock-drift nuisance, it is wrong.
# The station first reported 2026-08-01; anything before 2020 is corrupt, and
# anything meaningfully in the future is a console clock problem.
MIN_PLAUSIBLE = datetime(2020, 1, 1, tzinfo=timezone.utc)
FUTURE_TOLERANCE = timedelta(hours=2)


@dataclass(frozen=True)
class Observation:
    station_id: str
    ts_utc: datetime
    metric: str
    value_text: str
    value_num: float | None
    unit: str
    source: str = "observed"


@dataclass(frozen=True)
class Rejection:
    station_id: str
    ts_utc: datetime | None
    metric: str | None
    value_text: str | None
    unit: str | None
    reason: str


@dataclass
class NormalizeResult:
    observations: list[Observation]
    rejections: list[Rejection]
    observed_delta_s: int | None
    groups_seen: set[str]
    point_count: int

    @property
    def fetched(self) -> int:
        return len(self.observations) + len(self.rejections)


def _parse_float(text: str) -> float | None:
    """Cast defensively. Rejects NaN and infinity, which float() accepts."""
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(value) or math.isinf(value) else value


def _epoch_to_utc(key: Any) -> datetime | None:
    try:
        seconds = int(key)
    except (TypeError, ValueError):
        return None
    try:
        # tz-aware always. The naive form converts to host-local time, which
        # breaks across DST and on a retimed host (CLAUDE.md §5.3).
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def normalize_history(
    payload: Any,
    *,
    station_id: str,
    now: datetime,
    source: str = "observed",
) -> NormalizeResult:
    """Flatten a /device/history response into rows.

    Shape (confirmed in Phase 0): data.<group>.<metric> = {unit, list: {epoch: value}}
    """
    observations: list[Observation] = []
    rejections: list[Rejection] = []
    groups_seen: set[str] = set()
    all_stamps: set[int] = set()

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return NormalizeResult([], [], None, set(), 0)

    for group, node in data.items():
        if not isinstance(node, dict):
            continue
        groups_seen.add(group)
        for metric_name, leaf in node.items():
            if not isinstance(leaf, dict):
                continue
            metric = f"{group}.{metric_name}"
            unit = leaf.get("unit")
            series = leaf.get("list")
            if not isinstance(series, dict):
                continue
            if not isinstance(unit, str):
                rejections.append(
                    Rejection(station_id, None, metric, None, None, "missing unit on metric")
                )
                continue

            for raw_key, raw_value in series.items():
                ts = _epoch_to_utc(raw_key)
                text = "" if raw_value is None else str(raw_value)

                if ts is None:
                    rejections.append(
                        Rejection(
                            station_id, None, metric, text, unit, f"unparseable epoch {raw_key!r}"
                        )
                    )
                    continue
                if ts < MIN_PLAUSIBLE:
                    rejections.append(
                        Rejection(station_id, ts, metric, text, unit, "timestamp implausibly old")
                    )
                    continue
                if ts > now + FUTURE_TOLERANCE:
                    rejections.append(
                        Rejection(
                            station_id,
                            ts,
                            metric,
                            text,
                            unit,
                            "timestamp in the future (console clock drift)",
                        )
                    )
                    continue
                if not text.strip():
                    rejections.append(Rejection(station_id, ts, metric, text, unit, "empty value"))
                    continue

                all_stamps.add(int(raw_key))
                observations.append(
                    Observation(
                        station_id=station_id,
                        ts_utc=ts,
                        metric=metric,
                        value_text=text,
                        value_num=_parse_float(text),
                        unit=unit,
                        source=source,
                    )
                )

    return NormalizeResult(
        observations=observations,
        rejections=rejections,
        observed_delta_s=median_delta(sorted(all_stamps)),
        groups_seen=groups_seen,
        point_count=len(all_stamps),
    )


def median_delta(stamps: list[int]) -> int | None:
    """Median spacing between consecutive timestamps, in seconds.

    This is the only thing standing between us and D2's silent downgrade: the
    response never states its own resolution, so it has to be measured.
    """
    if len(stamps) < 2:
        return None
    deltas = [b - a for a, b in zip(stamps, stamps[1:], strict=False)]
    return int(statistics.median(deltas))


def duplicate_keys(observations: list[Observation]) -> list[Observation]:
    """Rows sharing a natural key within one payload.

    The primary key would reject the second one anyway, but as a constraint
    violation that aborts the whole load. Detecting them here means they can be
    quarantined with a reason (§10) instead of taking the run down.
    """
    seen: set[tuple[str, datetime, str]] = set()
    dupes: list[Observation] = []
    for obs in observations:
        key = (obs.station_id, obs.ts_utc, obs.metric)
        if key in seen:
            dupes.append(obs)
        else:
            seen.add(key)
    return dupes
