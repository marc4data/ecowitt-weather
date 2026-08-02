"""Parse-check the Phase 1 DDL.

No Postgres instance exists yet, so this validates *syntax only*. It cannot
catch a semantic error, and sqlglot falls back to generic parsing for plpgsql
bodies — so the immutability trigger is not meaningfully checked here.
Execute against a scratch database before trusting any of it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlglot

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schema"
SCHEMA_FILES = sorted(SCHEMA_DIR.glob("*.sql"))


def _executable_sql(path: Path) -> str:
    """Drop comment lines — the files carry illustrative DML in comments."""
    return "\n".join(
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.strip().startswith("--")
    )


def test_schema_files_exist():
    assert SCHEMA_FILES, "no schema/*.sql found"


@pytest.mark.parametrize("path", SCHEMA_FILES, ids=lambda p: p.name)
def test_schema_parses_as_postgres(path: Path):
    statements = [s for s in sqlglot.parse(_executable_sql(path), dialect="postgres") if s]
    assert statements, f"{path.name} produced no statements"


@pytest.mark.parametrize("path", SCHEMA_FILES, ids=lambda p: p.name)
def test_schema_carries_unexecuted_warning(path: Path):
    """Neither option may lose its 'not yet executed' caveat by accident."""
    assert "not yet executed" in path.read_text(encoding="utf-8").lower()
