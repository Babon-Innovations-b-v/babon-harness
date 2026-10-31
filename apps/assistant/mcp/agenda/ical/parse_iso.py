"""parse_iso(), ISO8601 string → timezone-aware UTC datetime.

Accepts the ``Z`` suffix (datetime.fromisoformat pre-3.11 rejects it),
explicit offsets, and naive strings (treated as UTC, the contract every
MCP tool documents).
"""
from __future__ import annotations

from datetime import datetime

from .utc import utc


def parse_iso(value: str) -> datetime:
    """Accept ISO8601 with or without timezone. Naive = UTC."""
    cleaned = value.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    dt = datetime.fromisoformat(cleaned)
    return utc(dt)
