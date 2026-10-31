"""utc(), coerce a datetime to timezone-aware UTC.

Shared by the sibling ical modules (promoted out of the former private
``_time.py``: a helper imported by five files
is a seam, not an internal). The ISO-string projection lives in ``iso.py``.
"""
from __future__ import annotations

from datetime import datetime, timezone


def utc(dt: datetime) -> datetime:
    """Coerce to UTC. Naive datetime → assumed UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
