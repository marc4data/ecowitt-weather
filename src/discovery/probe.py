"""Granularity probe — Phase 0 deliverable D2.

Answers the open risk in CLAUDE.md §6: at what span does `cycle_type=5min`
stop being honored, and when it is not honored, does the API reject the request
or silently return coarser data?

Two API behaviors discovered before this probe was written shape it:

1. `start_date`/`end_date` are interpreted in **console-local** time, while
   returned epochs are **UTC**. Framing the request in UTC yields `code=0`
   with an empty body — a silent miss, not an error. Every request here is
   therefore framed in console-local time, using an offset detected at runtime
   rather than hardcoded.
2. `call_back=all` is rejected by /device/history (code 40016). History
   requires explicit field or group selection.

Get either wrong and the probe measures nothing while reporting success.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .client import DiscoveryError, EcowittClient, RawResponse

# One cheap, always-present metric. Keeps probe responses small so that
# timing and size measurements reflect span, not field count.
PROBE_CALL_BACK = "outdoor.temperature"

# Nominal seconds-per-point for each cycle_type, used to decide whether the
# returned spacing matches what was asked for.
EXPECTED_DELTA_S = {"5min": 300, "30min": 1800, "4hour": 14400, "1day": 86400}

SPANS: list[tuple[str, timedelta]] = [
    ("1h", timedelta(hours=1)),
    ("6h", timedelta(hours=6)),
    ("24h", timedelta(hours=24)),
    ("48h", timedelta(hours=48)),
    ("7d", timedelta(days=7)),
    ("30d", timedelta(days=30)),
    ("90d", timedelta(days=90)),
]

CYCLE_TYPES = ["5min", "auto"]

# 24-hour windows at increasing age, probing the retention tiers in §6.
RETENTION_AGES_DAYS = [30, 100, 400]


@dataclass
class ProbeResult:
    kind: str
    cycle_type: str
    span_label: str
    window_start_utc: datetime
    window_end_utc: datetime
    http_status: int | None = None
    api_code: Any | None = None
    api_message: Any | None = None
    point_count: int = 0
    median_delta_s: float | None = None
    min_delta_s: int | None = None
    max_delta_s: int | None = None
    first_point_utc: datetime | None = None
    last_point_utc: datetime | None = None
    body_bytes: int = 0
    duration_s: float = 0.0
    raw_file: str = ""
    error: str | None = None

    @property
    def honored(self) -> str:
        """Did the returned spacing match the cycle_type requested?"""
        if self.error or self.point_count == 0:
            return "n/a"
        expected = EXPECTED_DELTA_S.get(self.cycle_type)
        if expected is None:
            return f"auto -> {self._describe_actual()}"
        if self.median_delta_s is None:
            return "single point"
        # Tolerate jitter; the tiers are far enough apart that 20% is safe.
        return (
            "yes"
            if abs(self.median_delta_s - expected) <= expected * 0.2
            else (f"NO -> {self._describe_actual()}")
        )

    def _describe_actual(self) -> str:
        if self.median_delta_s is None:
            return "single point"
        for name, seconds in EXPECTED_DELTA_S.items():
            if abs(self.median_delta_s - seconds) <= seconds * 0.2:
                return name
        return f"{self.median_delta_s:.0f}s"


def resolve_console_tz(client: EcowittClient) -> tuple[tzinfo, str]:
    """Get the console's timezone, preferring the API's own answer.

    `/device/info` reports `date_zone_id` as an IANA name (e.g.
    `America/Chicago`). That is strictly better than measuring an offset:
    a fixed offset is correct only until the next DST transition, and is
    already wrong for any *historical* window that straddles one — which is
    exactly what backfill does. Falls back to measurement if the field is
    missing or names a zone this host does not know.

    Returns the timezone and a short provenance string for the report.
    """
    try:
        response = client.device_info(label="tz-device-info")
        data = response.payload.get("data") if isinstance(response.payload, dict) else None
        zone_name = (data or {}).get("date_zone_id") if isinstance(data, dict) else None
        if zone_name:
            return ZoneInfo(str(zone_name)), f"/device/info date_zone_id={zone_name}"
    except (DiscoveryError, ZoneInfoNotFoundError, ValueError):
        pass

    offset = detect_console_utc_offset(client)
    hours = offset.total_seconds() / 3600
    return timezone(offset), f"measured empirically ({hours:+.2f} h, no DST rules)"


def detect_console_utc_offset(client: EcowittClient) -> timedelta:
    """Determine the console's UTC offset empirically, in one request.

    Sends a wide window in the past framed *as if* the date strings were UTC.
    The API reads them as console-local, so the data that comes back is shifted
    by exactly the console's offset. Comparing the returned UTC edge against
    what was requested recovers that offset.

    Hardcoding this would be wrong twice over: the console's timezone is a user
    setting that need not match this host, and it shifts under DST.

    The window is deliberately recent. This station's history reaches back only
    about a day, so a window placed further back returns nothing and the offset
    cannot be recovered from it. Pass `--console-offset` to skip this entirely.
    """
    anchor = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    end = anchor - timedelta(hours=12)
    start = anchor - timedelta(hours=18)

    response = client.history(
        start_date=start,
        end_date=end,
        cycle_type="auto",
        call_back=PROBE_CALL_BACK,
        label="offset-detect",
    )
    stamps = _timestamps(response)
    if not stamps:
        raise DiscoveryError(
            "Could not detect the console UTC offset: the detection window returned no "
            f"data. Inspect {response.raw_path}. Re-run with --console-offset=<hours> "
            "to pin it manually."
        )

    # The date string S is read as console-local, so the absolute instant it
    # denotes is `S - offset`. The request therefore clipped the data to
    # [start - offset, end - offset], and the leading edge of what came back
    # sits `-offset` away from what we sent. Note the negation: the measured
    # shift is the inverse of the console's UTC offset, and getting this
    # backwards silently doubles the error instead of cancelling it.
    observed = datetime.fromtimestamp(min(stamps), tz=timezone.utc)
    quarter_hours = round((observed - start).total_seconds() / 900)
    offset = -timedelta(seconds=quarter_hours * 900)

    # A derived offset outside the range of real world timezones means the
    # leading edge was clipped by data availability rather than by the request.
    if not timedelta(hours=-12) <= offset <= timedelta(hours=14):
        raise DiscoveryError(
            f"Detected console offset {offset} is outside UTC-12..UTC+14, so the "
            "detection window was clipped by missing data rather than by the request. "
            "Re-run with --console-offset=<hours>."
        )
    return offset


def _timestamps(response: RawResponse) -> list[int]:
    """Pull the epoch keys out of a history response. Never casts blindly."""
    payload = response.payload
    if not isinstance(payload, dict):
        return []
    node: Any = payload.get("data")
    if not isinstance(node, dict):
        return []

    stamps: list[int] = []

    def walk(item: Any) -> None:
        if not isinstance(item, dict):
            return
        series = item.get("list")
        if isinstance(series, dict):
            for key in series:
                try:
                    stamps.append(int(key))
                except (TypeError, ValueError):
                    continue
            return
        for value in item.values():
            walk(value)

    walk(node)
    return stamps


def _measure(
    client: EcowittClient,
    *,
    kind: str,
    cycle_type: str,
    span_label: str,
    start_utc: datetime,
    end_utc: datetime,
    console_tz: tzinfo,
) -> ProbeResult:
    result = ProbeResult(
        kind=kind,
        cycle_type=cycle_type,
        span_label=span_label,
        window_start_utc=start_utc,
        window_end_utc=end_utc,
    )

    try:
        response = client.history(
            start_date=start_utc.astimezone(console_tz),
            end_date=end_utc.astimezone(console_tz),
            cycle_type=cycle_type,
            call_back=PROBE_CALL_BACK,
            label=f"probe-{kind}-{cycle_type}-{span_label}",
        )
    except DiscoveryError as exc:
        result.error = str(exc)
        return result

    result.http_status = response.http_status
    result.api_code = response.api_code
    result.api_message = response.api_message
    result.body_bytes = response.body_bytes
    result.duration_s = response.duration_s
    result.raw_file = response.raw_path.name
    if response.parse_error:
        result.error = f"unparseable body: {response.parse_error}"
        return result

    stamps = sorted(set(_timestamps(response)))
    result.point_count = len(stamps)
    if stamps:
        result.first_point_utc = datetime.fromtimestamp(stamps[0], tz=timezone.utc)
        result.last_point_utc = datetime.fromtimestamp(stamps[-1], tz=timezone.utc)
    deltas = [b - a for a, b in zip(stamps, stamps[1:], strict=False)]
    if deltas:
        result.median_delta_s = statistics.median(deltas)
        result.min_delta_s = min(deltas)
        result.max_delta_s = max(deltas)
    return result


@dataclass
class ProbeRun:
    console_tz: tzinfo
    tz_source: str = ""
    results: list[ProbeResult] = field(default_factory=list)

    @property
    def max_honored_span(self) -> str:
        """Largest span whose 5min request came back at 5min spacing."""
        honored = [
            r.span_label
            for r in self.results
            if r.kind == "span" and r.cycle_type == "5min" and r.honored == "yes"
        ]
        return honored[-1] if honored else "none"

    @property
    def silent_downgrade(self) -> bool:
        return any(
            r.kind == "span"
            and r.cycle_type == "5min"
            and r.honored.startswith("NO")
            and r.api_code in (0, "0")
            for r in self.results
        )

    @property
    def earliest_seen(self) -> datetime | None:
        """Oldest observation any probe returned — a floor on station history."""
        seen = [r.first_point_utc for r in self.results if r.first_point_utc]
        return min(seen) if seen else None

    def retention_verdict(self, result: ProbeResult) -> str:
        """Distinguish an API retention limit from a station that is simply new.

        An empty window whose end predates the oldest observation we have seen
        anywhere says nothing about retention — there was never data there to
        retain. Reporting it as a retention finding would be a lie.
        """
        if result.point_count:
            return result.honored
        earliest = self.earliest_seen
        if earliest and result.window_end_utc < earliest:
            return "VOID — predates station history"
        return "empty (code 0)"


def run(
    client: EcowittClient,
    *,
    console_tz: tzinfo | None = None,
    tz_source: str = "",
) -> ProbeRun:
    if console_tz is None:
        console_tz, tz_source = resolve_console_tz(client)
    run_state = ProbeRun(console_tz=console_tz, tz_source=tz_source)

    anchor = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

    # Ascending span: if 5min stops being honored early, that is known before
    # the largest and slowest requests are issued.
    for span_label, span in SPANS:
        for cycle_type in CYCLE_TYPES:
            run_state.results.append(
                _measure(
                    client,
                    kind="span",
                    cycle_type=cycle_type,
                    span_label=span_label,
                    start_utc=anchor - span,
                    end_utc=anchor,
                    console_tz=console_tz,
                )
            )

    for age_days in RETENTION_AGES_DAYS:
        end = anchor - timedelta(days=age_days)
        run_state.results.append(
            _measure(
                client,
                kind="retention",
                cycle_type="5min",
                span_label=f"{age_days}d ago",
                start_utc=end - timedelta(hours=24),
                end_utc=end,
                console_tz=console_tz,
            )
        )

    return run_state


def render_markdown(run_state: ProbeRun, *, generated_at: datetime) -> str:
    lines: list[str] = [
        "# D2 — Granularity probe results",
        "",
        f"Generated {generated_at.isoformat()} · `call_back={PROBE_CALL_BACK}`",
        "",
        f"Console timezone: **{run_state.console_tz}** ({run_state.tz_source}). All request",
        "windows below were framed in console-local time; all timestamps shown are UTC.",
        "",
        "## Span sweep",
        "",
        "| cycle_type | span | HTTP | code | points | median Δ | min Δ | max Δ "
        "| honored? | bytes | secs |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]

    def row(r: ProbeResult) -> str:
        med = f"{r.median_delta_s:.0f}s" if r.median_delta_s is not None else "—"
        return (
            f"| `{r.cycle_type}` | {r.span_label} | {r.http_status} | {r.api_code} "
            f"| {r.point_count:,} | {med} | {r.min_delta_s or '—'} | {r.max_delta_s or '—'} "
            f"| {r.honored} | {r.body_bytes:,} | {r.duration_s:.1f} |"
        )

    lines += [row(r) for r in run_state.results if r.kind == "span"]
    lines += [
        "",
        "## Retention probes (24 h windows, `cycle_type=5min`)",
        "",
        "| age | HTTP | code | points | median Δ | honored? | window (UTC) |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in run_state.results:
        if r.kind != "retention":
            continue
        med = f"{r.median_delta_s:.0f}s" if r.median_delta_s is not None else "—"
        window = f"{r.window_start_utc:%Y-%m-%d %H:%M} → {r.window_end_utc:%H:%M}"
        lines.append(
            f"| {r.span_label} | {r.http_status} | {r.api_code} | {r.point_count:,} "
            f"| {med} | {run_state.retention_verdict(r)} | {window} |"
        )

    earliest = run_state.earliest_seen
    earliest_text = earliest.isoformat() if earliest else "unknown"
    lines += [
        "",
        f"> **Oldest observation returned by any probe: {earliest_text}.**",
        "> Windows ending before that are marked VOID: they measure the station's age,",
        "> not the API's retention policy. The retention tiers in CLAUDE.md §6 remain",
        "> UNVERIFIED and must be re-probed once the station has months of history.",
        "",
        "## Conclusions",
        "",
        f"- **Maximum span for which `cycle_type=5min` is honored: {run_state.max_honored_span}.**",
        "  That is the backfill chunk size for Phase 1.",
        f"- **Silent downgrade observed: {'YES' if run_state.silent_downgrade else 'no'}.**",
    ]
    if run_state.silent_downgrade:
        lines.append(
            "  The API returned `code=0` with coarser spacing than requested. Phase 1 must "
            "verify returned timestamp spacing on every response and reject or re-chunk on "
            "mismatch — the request parameters cannot be trusted."
        )
    else:
        lines.append(
            "  Where `5min` was not honored the API signalled it rather than quietly "
            "returning coarser data. Spacing must still be verified per response."
        )
    lines.append("")
    return "\n".join(lines)
