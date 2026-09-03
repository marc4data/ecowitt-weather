"""Import the notebook modules that own the checks and the charts.

`notebooks/ecowitt_daily.py` holds every detection threshold and
`notebooks/ecowitt_nb.py` holds the fetching, palette and chart styling. The
email imports both rather than reimplementing either -- CLAUDE.md's own argument
against a sibling repo applies just as well inside one: two copies of the check
thresholds is the failure this project keeps designing against, and
`attention()` already carries the docstring "What a daily email keys off".

The notebooks directory is not an installed package, so it goes on `sys.path`
once, here, instead of in five modules. `ECOWITT_NOTEBOOK_DIR` overrides the
search for a deployment that puts the files somewhere else.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _notebook_dir() -> Path:
    if override := os.environ.get("ECOWITT_NOTEBOOK_DIR"):
        return Path(override)
    # src/reporting/shared.py -> src/reporting -> src -> repo root
    for base in (Path(__file__).resolve(), *Path(__file__).resolve().parents):
        candidate = base / "notebooks" / "ecowitt_daily.py"
        if candidate.is_file():
            return candidate.parent
    raise ModuleNotFoundError(
        "could not find notebooks/ecowitt_daily.py, which owns the check "
        "thresholds this report reads. Set ECOWITT_NOTEBOOK_DIR to the directory "
        "holding ecowitt_daily.py and ecowitt_nb.py."
    )


_DIR = str(_notebook_dir())
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

import ecowitt_daily as daily  # noqa: E402
import ecowitt_nb as nb  # noqa: E402

__all__ = ["daily", "nb"]
