"""Orchestration: fetch, verify, land, normalize, load.

The order matters and is not arbitrary:

    open run_log  ->  fetch  ->  LAND RAW  ->  verify resolution  ->  normalize
                  ->  quarantine  ->  load  ->  close run_log

Raw lands *before* verification, so a response that fails the resolution check
is still on disk to be inspected. Verification happens *before* normalisation,
so 30-minute data never reaches the curated table wearing a 5-minute label.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo

from discovery.client import EcowittClient

from . import config, db
from .normalize import NormalizeResult, Rejection, duplicate_keys, normalize_history


class ResolutionError(RuntimeError):
    """The API returned a coarser grid than requested, with code=0.

    D2's silent downgrade. This is a hard failure rather than a warning: data
    at the wrong resolution looks complete, and storing it once contaminates
    history in a way no later run can distinguish from real observations.
    """


@dataclass
class ChunkResult:
    counts: db.LoadCounts
    observed_delta_s: int | None
    point_count: int


def chunks(start: datetime, end: datetime, size: timedelta) -> list[tuple[datetime, datetime]]:
    """Split a window into <= size pieces. Never emits a zero-length chunk."""
    out: list[tuple[datetime, datetime]] = []
    cursor = start
    while cursor < end:
        stop = min(cursor + size, end)
        out.append((cursor, stop))
        cursor = stop
    return out


def verify_resolution(result: NormalizeResult, *, cycle_type: str) -> None:
    """Measure what came back and compare it to what was asked for.

    A single point cannot establish spacing, so it is accepted -- a 4-hour
    window that returns one point is a gap, not a downgrade, and the gap sweep
    is what handles that.
    """
    if cycle_type != config.CYCLE_TYPE or result.observed_delta_s is None:
        return
    drift = abs(result.observed_delta_s - config.EXPECTED_DELTA_S)
    if drift > config.DELTA_TOLERANCE_S:
        raise ResolutionError(
            f"requested cycle_type={cycle_type} (expected ~{config.EXPECTED_DELTA_S}s "
            f"spacing) but the response has median spacing {result.observed_delta_s}s "
            f"across {result.point_count} points. The API downgraded silently and "
            f"still returned code=0. Refusing to store it."
        )


def verify_groups(result: NormalizeResult, requested: list[str]) -> list[str]:
    """An unknown group name returns code=0 with empty data, so check.

    Returned rather than raised: a genuinely silent sensor is indistinguishable
    from a typo here, and taking the run down over a quiet battery channel
    would be worse than recording it.
    """
    return sorted(set(requested) - result.groups_seen)


def fetch_and_load(
    client: EcowittClient,
    conn,
    *,
    run_id: str,
    station_id: str,
    console_tz: tzinfo,
    start_utc: datetime,
    end_utc: datetime,
    label: str,
    source: str = "observed",
) -> ChunkResult:
    """One chunk, end to end."""
    response = client.history(
        start_date=start_utc.astimezone(console_tz),
        end_date=end_utc.astimezone(console_tz),
        cycle_type=config.CYCLE_TYPE,
        call_back=",".join(config.HISTORY_GROUPS),
        label=label,
        **config.UNIT_PARAMS,
    )

    # Land first. Everything below can fail; the payload must survive that.
    raw_id = db.land_raw(
        conn,
        run_id=run_id,
        endpoint="device/history",
        label=label,
        requested_at=response.requested_at,
        request_url=response.redacted_url,
        http_status=response.http_status,
        api_code=response.api_code,
        api_message=response.api_message,
        body_bytes=response.raw_path.read_bytes(),
        duration_s=response.duration_s,
    )
    response.raise_if_failed()

    result = normalize_history(
        response.payload, station_id=station_id, now=db.utcnow(), source=source
    )
    verify_resolution(result, cycle_type=config.CYCLE_TYPE)

    rejections: list[Rejection] = list(result.rejections)
    dupes = duplicate_keys(result.observations)
    if dupes:
        dup_keys = {(d.station_id, d.ts_utc, d.metric) for d in dupes}
        rejections += [
            Rejection(
                d.station_id,
                d.ts_utc,
                d.metric,
                d.value_text,
                d.unit,
                "duplicate natural key within one payload",
            )
            for d in dupes
        ]
        seen: set[tuple] = set()
        deduped = []
        for obs in result.observations:
            key = (obs.station_id, obs.ts_utc, obs.metric)
            if key in dup_keys and key in seen:
                continue
            seen.add(key)
            deduped.append(obs)
        result.observations = deduped

    counts = db.load_observations(conn, result.observations, run_id=run_id)
    counts.rejected = db.quarantine(conn, rejections, run_id=run_id, raw_id=raw_id)
    return ChunkResult(counts, result.observed_delta_s, result.point_count)
