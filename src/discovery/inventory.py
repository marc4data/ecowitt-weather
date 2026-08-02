"""Field inventory — Phase 0 deliverable D3 (§7).

Split in two on purpose:

* `collect()` makes the API calls and does nothing else. It needs ~15 minutes
  of wall clock because §7 wants real-time samples ≥5 minutes apart, and a
  process that long should not also hold the analysis.
* `build()` reads the captures back off disk. It makes no requests, so the
  inventory can be regenerated and corrected without touching the API — and it
  proves the raw captures are genuinely sufficient, which is the claim §10
  makes when it says parsing bugs are recoverable but discarded data is not.

Only captures labelled `d3-*` are analysed. The unit sweeps (D4) deliberately
varied `temp_unitid`, so folding them in would report `℃` and `ºF` for the same
field and misrepresent what this station reports by default.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any

from .client import EcowittClient

# History rejects call_back=all, so the groups this station actually reports
# are listed explicitly. A group name that does not exist returns code=0 with
# empty data rather than an error, so this list must be checked against what
# comes back rather than assumed correct.
HISTORY_GROUPS = [
    "outdoor",
    "indoor",
    "solar_and_uvi",
    "rainfall_piezo",
    "wind",
    "pressure",
    "temp_and_humidity_ch1",
    "temp_and_humidity_ch2",
    "temp_and_humidity_ch3",
    "soil_ch1",
    "soil_ch2",
    "battery",
]

REALTIME = "real_time"
HISTORY = "history"


@dataclass
class FieldStat:
    path: str
    endpoints: set[str] = field(default_factory=set)
    raw_types: set[str] = field(default_factory=set)
    units: set[str] = field(default_factory=set)
    examples: list[str] = field(default_factory=list)
    observations: int = 0
    null_or_blank: int = 0
    float_failures: list[str] = field(default_factory=list)
    distinct_values: set[str] = field(default_factory=set)

    def record(self, endpoint: str, value: Any, unit: Any) -> None:
        self.endpoints.add(endpoint)
        self.raw_types.add(type(value).__name__)
        if unit is not None:
            self.units.add(unit)
        self.observations += 1

        if value is None or (isinstance(value, str) and not value.strip()):
            self.null_or_blank += 1
            return

        text = str(value)
        self.distinct_values.add(text)
        if len(self.examples) < 3 and text not in self.examples:
            self.examples.append(text)
        try:
            float(text)
        except (TypeError, ValueError):
            if len(self.float_failures) < 3:
                self.float_failures.append(text)

    @property
    def parses_as_float(self) -> str:
        if self.float_failures:
            return f"**no** — e.g. {', '.join(repr(v) for v in self.float_failures)}"
        return "yes"

    @property
    def null_rate(self) -> str:
        if not self.observations:
            return "—"
        return f"{self.null_or_blank}/{self.observations}"

    @property
    def constant(self) -> bool:
        """Never varied across every observation — a placeholder-channel smell."""
        return self.observations > 2 and len(self.distinct_values) == 1


def collect(
    client: EcowittClient,
    *,
    count: int,
    interval_s: int,
    console_tz: tzinfo,
    log=print,
) -> None:
    """Take `count` real-time samples `interval_s` apart, plus one 24 h history."""
    for index in range(count):
        if index:
            log(f"  waiting {interval_s}s before sample {index + 1}/{count} ...")
            time.sleep(interval_s)
        response = client.real_time(label=f"d3-realtime-{index + 1}")
        log(
            f"  sample {index + 1}/{count}: code={response.api_code} "
            f"{response.body_bytes:,} bytes -> {response.raw_path.name}"
        )

    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=24)
    response = client.history(
        start_date=start.astimezone(console_tz),
        end_date=end.astimezone(console_tz),
        cycle_type="5min",
        call_back=",".join(HISTORY_GROUPS),
        label="d3-history-24h",
    )
    log(
        f"  history 24h: code={response.api_code} {response.body_bytes:,} bytes "
        f"-> {response.raw_path.name}"
    )


def _walk_realtime(data: dict, stats: dict[str, FieldStat]) -> None:
    for group, node in data.items():
        if not isinstance(node, dict):
            continue
        for metric, leaf in node.items():
            if not isinstance(leaf, dict):
                continue
            path = f"data.{group}.{metric}"
            stats.setdefault(path, FieldStat(path)).record(
                REALTIME, leaf.get("value"), leaf.get("unit")
            )


def _walk_history(data: dict, stats: dict[str, FieldStat]) -> None:
    for group, node in data.items():
        if not isinstance(node, dict):
            continue
        for metric, leaf in node.items():
            if not isinstance(leaf, dict):
                continue
            series = leaf.get("list")
            path = f"data.{group}.{metric}"
            stat = stats.setdefault(path, FieldStat(path))
            if not isinstance(series, dict):
                stat.record(HISTORY, None, leaf.get("unit"))
                continue
            for value in series.values():
                stat.record(HISTORY, value, leaf.get("unit"))


def build(raw_dir: Path, *, prefix: str = "d3-") -> tuple[dict[str, FieldStat], dict[str, int]]:
    """Read captures back off disk. Makes no API calls."""
    stats: dict[str, FieldStat] = {}
    counts: dict[str, int] = defaultdict(int)

    for path in sorted(raw_dir.glob("*.json")):
        if path.name.endswith(".meta.json"):
            continue
        meta_path = path.with_name(path.name[:-5] + ".meta.json")
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not str(meta.get("label", "")).startswith(prefix):
            continue

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            counts["unparseable"] += 1
            continue

        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            continue

        if "real_time" in str(meta.get("endpoint", "")):
            counts[REALTIME] += 1
            _walk_realtime(data, stats)
        else:
            counts[HISTORY] += 1
            _walk_history(data, stats)

    return stats, dict(counts)


def render_markdown(
    stats: dict[str, FieldStat], counts: dict[str, int], *, generated_at: datetime
) -> str:
    realtime_only = sorted(p for p, s in stats.items() if s.endpoints == {REALTIME})
    history_only = sorted(p for p, s in stats.items() if s.endpoints == {HISTORY})
    constants = sorted(p for p, s in stats.items() if s.constant)
    non_float = sorted(p for p, s in stats.items() if s.float_failures)

    lines = [
        "# D3 — Field inventory",
        "",
        f"Generated {generated_at.isoformat()} from captures on disk — no API calls.",
        "",
        f"Sources: {counts.get(REALTIME, 0)} real-time capture(s), "
        f"{counts.get(HISTORY, 0)} history capture(s). "
        f"{len(stats)} distinct field paths.",
        "",
        "| field path | endpoints | raw type | examples | unit | null rate | float? |",
        "|---|---|---|---|---|---|---|",
    ]
    for path in sorted(stats):
        stat = stats[path]
        units = ", ".join(f"`{u}`" for u in sorted(stat.units)) if stat.units else "—"
        examples = ", ".join(f"`{v}`" for v in stat.examples) or "—"
        lines.append(
            f"| `{path}` | {', '.join(sorted(stat.endpoints))} "
            f"| {', '.join(sorted(stat.raw_types))} | {examples} | {units} "
            f"| {stat.null_rate} | {stat.parses_as_float} |"
        )

    lines += ["", "## Endpoint asymmetry", ""]
    if realtime_only:
        lines += [
            f"**Present in real-time but not history ({len(realtime_only)}):**",
            "",
            *[f"- `{p}`" for p in realtime_only],
            "",
        ]
    if history_only:
        lines += [
            f"**Present in history but not real-time ({len(history_only)}):**",
            "",
            *[f"- `{p}`" for p in history_only],
            "",
        ]
    if not realtime_only and not history_only:
        lines += ["Both endpoints returned the same field set.", ""]

    lines += [
        "## Fields that never varied",
        "",
        "Constant across every observation. Candidates for placeholder or",
        "zero-filled channels rather than real attached sensors — but a genuinely",
        "still sensor looks identical over a short window, so this is a flag for",
        "review, not a conclusion.",
        "",
    ]
    lines += [f"- `{p}` (always `{next(iter(stats[p].distinct_values))}`)" for p in constants] or [
        "None."
    ]

    lines += ["", "## Values that do not parse as float", ""]
    lines += [f"- `{p}`: {stats[p].parses_as_float}" for p in non_float] or [
        "None — every observed value parsed."
    ]

    lines += [
        "",
        "## Notes for the user",
        "",
        "- `soil_chN.ad` is an unexplained raw ADC-style reading alongside",
        "  `soilmoisture`. Its meaning and scale need confirming before it is",
        "  stored as anything but an opaque number.",
        "- `outdoor.vpd` (vapour pressure deficit) is reported in `inHg` and is",
        "  **not** in the published field list.",
        "- `rainfall_piezo.1_hour` is named `hourly` in the published docs. The",
        "  wire name is authoritative.",
        "- `battery.*` mixes volts with unitless status codes; the unitless ones",
        "  are not measurements and should not be resampled.",
        "",
    ]
    return "\n".join(lines)
