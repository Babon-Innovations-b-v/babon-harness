"""Event, the in-process calendar-event shape used by the MCP tools.

Owns the field set and the JSON projection (``to_dict``) only; building and
parsing VCALENDAR blobs live in ``build_vcal.py`` / ``parse_vcal.py``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .iso import iso


@dataclass
class Event:
    uid: str
    title: str
    start: datetime
    end: datetime
    description: str | None = None
    location: str | None = None
    rrule: str | None = None  # raw RRULE string, e.g. "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO"
    calendar: str | None = None  # informational; set when reading

    def to_dict(self) -> dict:
        """JSON-serialisable shape exposed to MCP tool callers."""
        return {
            "uid": self.uid,
            "title": self.title,
            "start": iso(self.start),
            "end": iso(self.end),
            "description": self.description,
            "location": self.location,
            "rrule": self.rrule,
            "calendar": self.calendar,
        }
