"""SQL identifier allowlist shared by every dashkit table-name seam.

dashkit tables are parameterised by name (``{domain}_activity``,
``{domain}_ai_calls``, ``{domain}_sync_status``); names interpolate into
DDL/DML f-strings, so every name passes this gate first.
"""
from __future__ import annotations

import re


def validate_table_name(name: str) -> None:
    """Reject anything that isn't a plain [a-z_][a-z0-9_]* identifier."""
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", name):
        raise ValueError(f"invalid table name: {name!r}")
