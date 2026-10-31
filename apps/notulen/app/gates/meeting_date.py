"""Meeting-date gate for POST /api/upload/start.

FAILURE POLICY: dashboard gates raise ``HTTPException`` with user copy;
nothing is swallowed.
"""
from __future__ import annotations

from datetime import date

from fastapi import HTTPException


def parse_meeting_date(raw: str) -> date:
    """Parse YYYY-MM-DD or raise HTTP 400."""
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format, use YYYY-MM-DD")
