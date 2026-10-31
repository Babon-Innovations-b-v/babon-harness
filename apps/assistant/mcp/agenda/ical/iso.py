"""iso(), datetime → UTC ISO8601 string (the inverse of ``parse_iso.py``).

Shared by the sibling ical modules (promoted out of the former private
``_time.py``). UTC coercion itself lives in
``utc.py``.
"""
from __future__ import annotations

from datetime import datetime

from .utc import utc


def iso(dt: datetime) -> str:
    """Serialise as an ISO8601 string in UTC."""
    return utc(dt).isoformat()
