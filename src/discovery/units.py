"""Unit parameter verification — Phase 0 deliverable D4 (§8).

The unit IDs are discovered from the API itself rather than read from the
documentation. That was not the original plan, but the doc has now been wrong
about this API three times (`call_back=all` on history, the `hourly` field
name, the set of fields `outdoor` returns), so a source that can be verified
beats a source that must be trusted.

The discovery trick: an out-of-range value makes the API state its own valid
range in the error message —

    temp_unitid=0  ->  code 40000, "temp_unitid must between 1 - 2"

so one probe per parameter bounds the sweep, and the sweep records what unit
string each ID actually produces. That closes CLAUDE.md §5.1's requirement to
pin units explicitly and assert what comes back, without guessing a single
value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .client import EcowittClient

_RANGE_RE = re.compile(r"between\s+(\d+)\s*-\s*(\d+)")

# Metrics used to observe each parameter's effect. Several per family, because
# §8 asks whether the returned unit matches the request "for every metric" —
# one probe metric could not detect a family where the parameter is applied
# inconsistently.
UNIT_FAMILIES: dict[str, list[tuple[str, str]]] = {
    "temp_unitid": [
        ("outdoor", "temperature"),
        ("outdoor", "dew_point"),
        ("indoor", "temperature"),
        ("temp_and_humidity_ch1", "temperature"),
    ],
    "pressure_unitid": [("pressure", "relative"), ("pressure", "absolute")],
    "wind_speed_unitid": [("wind", "wind_speed"), ("wind", "wind_gust")],
    "rainfall_unitid": [
        ("rainfall_piezo", "rain_rate"),
        ("rainfall_piezo", "daily"),
        ("rainfall_piezo", "yearly"),
    ],
    "solar_irradiance_unitid": [("solar_and_uvi", "solar")],
    # Governs the WFC/AC1100 water-flow and energy sub-devices, none of which
    # are attached here. There is no metric on this station it could change, so
    # it is swept for its valid range only — calling it "ignored" would be a
    # claim about the API when it is really a fact about our hardware.
    "capacity_unitid": [],
}


@dataclass
class UnitObservation:
    unit_id: int
    units_by_path: dict[str, str | None] = field(default_factory=dict)
    api_code: Any | None = None
    api_message: Any | None = None

    @property
    def distinct_units(self) -> list[str]:
        return sorted({u for u in self.units_by_path.values() if u is not None})


@dataclass
class UnitFamily:
    param: str
    low: int | None = None
    high: int | None = None
    range_message: str = ""
    observations: list[UnitObservation] = field(default_factory=list)

    @property
    def discovered(self) -> bool:
        return self.low is not None and self.high is not None

    @property
    def observable(self) -> bool:
        """Is there any metric on this station whose unit this could change?"""
        return bool(UNIT_FAMILIES.get(self.param))

    @property
    def honored(self) -> bool:
        """Did distinct IDs actually produce distinct units?

        If every ID yields the same string the parameter is being accepted and
        ignored — which would look like success while silently pinning nothing.
        """
        seen = [tuple(o.distinct_units) for o in self.observations if o.distinct_units]
        return len(set(seen)) > 1

    @property
    def verdict(self) -> str:
        if not self.discovered:
            return "range not discovered"
        if not self.observable:
            return "not observable on this station"
        return "yes" if self.honored else "**NO — accepted but ignored**"


def discover_range(client: EcowittClient, param: str) -> tuple[int | None, int | None, str]:
    """Bound a parameter by asking for something invalid and reading the complaint."""
    response = client.real_time(label=f"unitrange-{param}", **{param: 0})
    message = str(response.api_message or "")
    match = _RANGE_RE.search(message)
    if not match:
        return None, None, message
    return int(match.group(1)), int(match.group(2)), message


def sweep(client: EcowittClient, param: str) -> UnitFamily:
    family = UnitFamily(param=param)
    family.low, family.high, family.range_message = discover_range(client, param)
    if not family.discovered:
        return family

    paths = UNIT_FAMILIES.get(param, [])
    assert family.low is not None and family.high is not None
    for unit_id in range(family.low, family.high + 1):
        response = client.real_time(label=f"unit-{param}-{unit_id}", **{param: unit_id})
        observation = UnitObservation(
            unit_id=unit_id,
            api_code=response.api_code,
            api_message=response.api_message,
        )
        data = (response.payload or {}).get("data") if isinstance(response.payload, dict) else None
        for group, metric in paths:
            leaf = (data or {}).get(group, {}).get(metric, {}) if isinstance(data, dict) else {}
            observation.units_by_path[f"{group}.{metric}"] = (
                leaf.get("unit") if isinstance(leaf, dict) else None
            )
        family.observations.append(observation)
    return family


def run(client: EcowittClient) -> list[UnitFamily]:
    return [sweep(client, param) for param in UNIT_FAMILIES]


def _codepoints(text: str | None) -> str:
    if not text:
        return "—"
    exotic = " ".join(f"U+{ord(c):04X}" for c in text if ord(c) > 127)
    return exotic or "ascii"


def render_markdown(families: list[UnitFamily], *, generated_at: datetime) -> str:
    lines: list[str] = [
        "# D4 — API behavior notes",
        "",
        f"Generated {generated_at.isoformat()}",
        "",
        "## Unit parameters (§8)",
        "",
        "Valid ranges were not taken from the documentation. Each was obtained by",
        "sending an out-of-range value and reading the range back out of the API's own",
        "error message, then sweeping it.",
        "",
        "| parameter | valid IDs | ID → unit | parameter honored? |",
        "|---|---|---|---|",
    ]
    for fam in families:
        if not fam.discovered:
            lines.append(f"| `{fam.param}` | not discovered | — | message: {fam.range_message!r} |")
            continue
        mapping = "<br>".join(
            f"`{o.unit_id}` → " + (", ".join(f"`{u}`" for u in o.distinct_units) or "—")
            for o in fam.observations
        )
        lines.append(f"| `{fam.param}` | {fam.low}–{fam.high} | {mapping} | {fam.verdict} |")

    lines += [
        "",
        "### Exact encodings",
        "",
        "Unit strings become stored values, so they must round-trip byte-for-byte.",
        "",
        "| unit | non-ASCII codepoints |",
        "|---|---|",
    ]
    seen: dict[str, str] = {}
    for fam in families:
        for obs in fam.observations:
            for unit in obs.distinct_units:
                seen.setdefault(unit, _codepoints(unit))
    for unit, points in sorted(seen.items()):
        lines.append(f"| `{unit}` | {points} |")

    lines += [
        "",
        "> ⚠️ **The API is not internally consistent about degree signs.**",
        "> `temp_unitid=1` returns `℃` (U+2103 DEGREE CELSIUS) while `temp_unitid=2`",
        "> returns `ºF` (U+00BA MASCULINE ORDINAL INDICATOR + `F`) — two different",
        "> conventions from the same parameter. The published example response also",
        "> shows `℉` (U+2109) for a sub-device while using `ºF` for the main groups,",
        "> and mixes `µ` (U+00B5 MICRO SIGN) with `μ` (U+03BC GREEK SMALL LETTER MU).",
        "> Do not normalise these. Compare exactly, store exactly.",
        "",
        "## Unit ID numbering",
        "",
        "IDs are globally unique across parameters rather than per-parameter, and the",
        "observed families leave **17–23 unaccounted for**, implying unit parameters",
        "this project has not identified. `capacity_unitid` (24–26) was found by",
        "guessing the name, so name-guessing is the only discovery route for the gap.",
        "Absence of evidence here is not evidence of absence.",
        "",
    ]
    return "\n".join(lines)
