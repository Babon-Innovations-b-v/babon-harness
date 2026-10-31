"""parse_vcal(), parse a VCALENDAR blob into an Event.

Owns the bytes → Event direction only (the inverse of ``build_vcal.py``),
including the iCloud quirks: missing DTEND defaults to one hour, all-day
DTSTART dates become midnight UTC, and the RRULE dict is re-serialised to
the raw string form Event carries.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from icalendar import Calendar as IcsCalendar

from .utc import utc
from .event import Event


def parse_vcal(blob: bytes | str, calendar_name: str | None = None) -> Event:
    """Parse the first VEVENT in a VCALENDAR blob into an Event."""
    cal = IcsCalendar.from_ical(blob)
    for component in cal.walk("VEVENT"):
        return Event(
            uid=str(component.get("uid", "")),
            title=str(component.get("summary", "")),
            start=_to_datetime(component.get("dtstart").dt),
            end=_to_datetime(component.get("dtend").dt) if component.get("dtend") else _to_datetime(component.get("dtstart").dt) + timedelta(hours=1),
            description=_optional_str(component, "description"),
            location=_optional_str(component, "location"),
            rrule=_rrule_from_component(component),
            calendar=calendar_name,
        )
    raise ValueError("no VEVENT in calendar blob")


def _rrule_from_component(component) -> str | None:
    rrule = component.get("rrule")
    if not rrule:
        return None
    parts: list[str] = []
    for key, value in rrule.items():
        if isinstance(value, list):
            joined = ",".join(str(item) for item in value)
        else:
            joined = str(value)
        parts.append(f"{key.upper()}={joined}")
    return ";".join(parts)


def _optional_str(component, key: str) -> str | None:
    value = component.get(key)
    return str(value) if value else None


def _to_datetime(value) -> datetime:
    """All-day events (DTSTART = date) → midnight UTC. Else UTC-coerced."""
    if isinstance(value, datetime):
        return utc(value)
    return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
