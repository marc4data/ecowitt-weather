"""Phase 1 ingestion settings.

Everything here is a decision recorded in CLAUDE.md, not a tunable. Changing a
value silently changes the meaning of stored history, so each carries the date
it was decided and why.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta

# --- units (decided 2026-08-02) --------------------------------------------
# Imperial is canonical; metric is a derived view. Pinned per request rather
# than inherited from the console, because the console's unit setting is
# user-configurable, is not exposed by any API endpoint, and a silent change
# would corrupt history in a way that is very hard to detect later (§10).
#
# These IDs were discovered empirically, not read from the docs -- see
# samples/reports/api_behavior.md.
UNIT_PARAMS: dict[str, int] = {
    "temp_unitid": 2,  # ºF   (U+00BA, not U+00B0)
    "pressure_unitid": 4,  # inHg
    "wind_speed_unitid": 9,  # mph
    "rainfall_unitid": 13,  # in, in/hr
    "solar_irradiance_unitid": 16,  # W/m²
}

# --- what to fetch ---------------------------------------------------------
# History rejects call_back=all (code 40016), so groups are explicit. A group
# name that does not exist returns code=0 with empty data rather than an error,
# so the response is checked against this list rather than trusted.
HISTORY_GROUPS: list[str] = [
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

# --- cadence (decided 2026-08-02) ------------------------------------------
# Hourly pulls over a 4-hour window: each 5-minute point is fetched ~4 times
# before ageing out, so one failed pull loses nothing. Overlap is free because
# change detection counts unchanged rows instead of writing them (§7).
INCREMENTAL_WINDOW = timedelta(hours=4)

# 12 hours, NOT the 24 that D2 measured as the limit. Date parameters are read
# in console-local time, so on the spring-forward DST day a 24h *absolute*
# window becomes a 25h wall-clock span and silently downgrades to 30-minute
# data with code=0. 12h stays clear in both directions.
CHUNK = timedelta(hours=12)

# --- resolution verification ----------------------------------------------
# D2: cycle_type=5min is silently downgraded past a 24h span, always with
# code=0. Nothing in a response declares its own resolution, so the returned
# spacing must be measured on every response and compared. Never infer
# resolution from the request.
CYCLE_TYPE = "5min"
EXPECTED_DELTA_S = 300
DELTA_TOLERANCE_S = 60  # 300s grid with jitter; 30min would be 1800s, far outside


@dataclass(frozen=True)
class Settings:
    station_id: str
    dsn: str
    polite_delay_s: float = 2.0

    @classmethod
    def from_env(cls) -> Settings:
        """Read configuration. Fails loudly; never prompts, never defaults."""
        mac = (os.environ.get("ECOWITT_MAC") or "").strip()
        if not mac:
            raise RuntimeError("ECOWITT_MAC is not set")
        # Peer authentication over the unix socket: no password anywhere.
        dsn = os.environ.get("ECOWITT_DSN") or "dbname=ecowitt"
        return cls(station_id=mac, dsn=dsn)
