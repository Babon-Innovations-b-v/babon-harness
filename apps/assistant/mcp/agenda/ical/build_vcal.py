"""build_vcal(), render one Event into a VCALENDAR blob for save_event.

Owns the Event → bytes direction only; the inverse lives in
``parse_vcal.py``.
"""
from __future__ import annotations

from datetime import datetime, timezone

from icalendar import Calendar as IcsCalendar
from icalendar import Event as IcsEvent

from .utc import utc
from .event import Event


def build_vcal(event: Event) -> bytes:
    """Render an Event into a VCALENDAR blob ready for save_event."""
    cal = IcsCalendar()
    cal.add("prodid", "-//the team//harness-agenda MCP//EN")
    cal.add("version", "2.0")

    ics_event = IcsEvent()
    ics_event.add("uid", event.uid)
    ics_event.add("dtstamp", datetime.now(timezone.utc))
    ics_event.add("dtstart", utc(event.start))
    ics_event.add("dtend", utc(event.end))
    ics_event.add("summary", event.title)
    if event.description:
        ics_event.add("description", event.description)
    if event.location:
        ics_event.add("location", event.location)
    if event.rrule:
        ics_event.add("rrule", _rrule_to_dict(event.rrule))
    cal.add_component(ics_event)
    return cal.to_ical()


def _rrule_to_dict(raw: str) -> dict:
    """`icalendar` wants a dict, not a string. Split FREQ=WEEKLY;INTERVAL=2 into parts."""
    parts = {}
    for chunk in raw.split(";"):
        if "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        key = key.strip().upper()
        value = value.strip()
        if "," in value:
            parts[key] = [item.strip() for item in value.split(",")]
        else:
            parts[key] = value
    return parts
