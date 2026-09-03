"""A synthetic ACTION email, so "the alerting works" is demonstrated not assumed.

Ported from cfdb's `alerting_selftest_dag.py`, which fails on purpose to prove
alerts still arrive. The equivalent question here is narrower but the same in
kind: `--test` proves the report renders, and it proves nothing about whether
SMTP still authenticates, whether Gmail still accepts this sender, or whether
the address list on the VM is the one anybody thinks it is.

Deliberately needs NO DATABASE. The most valuable moment to ask "does the
alerting still work" is when something is broken, and requiring a healthy
database to find out would make the answer useless exactly when it matters.

Two safety properties, both structural rather than procedural:

  * It goes to the TEST list. `--selftest` resolves to test mode in the CLI and
    there is no flag that widens it.
  * It is labelled in the subject and at the top of both bodies, so nobody who
    receives one has to work out whether the house is actually on fire.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from . import config
from .report import Report, yesterday
from .shared import daily

_MEASURED = "96.4 ºF — above 85 ºF for 14 h from 09:00 · rooms agreeing: ch1, ch2"


def synthetic_report() -> Report:
    """An ACTION report with fabricated numbers, shaped exactly like a real one.

    The numbers are the 13-27 August 2026 incident rounded off, so the email
    exercises the real code path with realistic content rather than with
    placeholder text that could hide a formatting bug.
    """
    now = datetime.now(ZoneInfo(config.DISPLAY_ZONE))
    for_date = yesterday()

    checks = pd.DataFrame(
        [
            {
                "check": "indoor within protection band",
                "verdict": "FAIL",
                "measured": _MEASURED,
                "note": "SYNTHETIC. Minimum protection, not comfort: "
                f"{daily.PROTECT_MIN_F:.0f}–{daily.PROTECT_MAX_F:.0f} ºF.",
            },
            {
                "check": "grid coverage",
                "verdict": "PASS",
                "measured": "288/288 slots (100.0%)",
                "note": "SYNTHETIC.",
            },
            {
                "check": "sensors reporting recently",
                "verdict": "PASS",
                "measured": "all current",
                "note": "SYNTHETIC.",
            },
            {
                "check": "battery levels",
                "verdict": "PASS",
                "measured": "all above their floors",
                "note": "SYNTHETIC.",
            },
        ]
    )

    attention = {
        "severity": "alert",
        "headline": "synthetic self-test",
        "items": [
            {
                "check": "indoor within protection band",
                "verdict": "FAIL",
                "measured": _MEASURED,
                "note": checks.note.iloc[0],
                "days": 3,
                "action": config.GENERIC_ACTIONS.get("indoor within protection band"),
            }
        ],
        "resolved_earlier": [],
        "window_days": 7,
    }

    headlines = pd.DataFrame(
        [
            {"measure": "Outdoor High", "value": "101.4 ºF", "when": "4:20 PM"},
            {"measure": "Outdoor Low", "value": "74.8 ºF", "when": "6:35 AM"},
            {"measure": "Indoor High", "value": "96.4 ºF", "when": "6:05 PM"},
            {"measure": "Indoor Low", "value": "88.1 ºF", "when": "7:10 AM"},
            {"measure": "Rain Total", "value": "0.00 in", "when": "end of day"},
        ]
    )

    house = {
        "floor": daily.PROTECT_MIN_F,
        "ceiling": daily.PROTECT_MAX_F,
        "rh_ceiling": daily.PROTECT_RH_WARN,
        "low": 88.1,
        "high": 96.4,
        "last": 94.0,
        "rh_high": 51.0,
        "in_band": False,
        "breach_since": for_date - pd.Timedelta(days=2).to_pytimedelta(),
    }

    return Report(
        for_date=for_date,
        generated_at=now,
        mode="test",
        is_replay=False,
        zone=config.DISPLAY_ZONE,
        severity="alert",
        headline="synthetic self-test — no real condition",
        one_line=(
            "SELF-TEST. Nothing is wrong with the house. This email exists "
            "to prove that an ACTION email can still be built and delivered."
        ),
        has_data=True,
        checks=checks,
        attention=attention,
        headlines=headlines,
        comparison="Synthetic figures — this email describes no real day.",
        house=house,
        equipment=[
            {
                "metric": "battery.soilmoisture_sensor_ch1",
                "label": "soilmoisture_sensor_ch1",
                "value": 1.60,
                "verdict": "PASS",
                "held_days": 12,
                "basis": "derived",
                "sensor": "WH51 1xAA",
            }
        ],
        actions=[
            config.GENERIC_ACTIONS["indoor within protection band"],
            "Then ignore it — this is a self-test, not a real condition.",
        ],
        is_selftest=True,
    )
