"""create_event tool, write a new event into a named calendar."""
from __future__ import annotations

from ..ical import Event, build_vcal, new_uid, parse_iso
from ..runtime import ensure_client


def create_event(
    title: str,
    start: str,
    end: str,
    calendar: str,
    description: str | None = None,
    location: str | None = None,
    rrule: str | None = None,
) -> dict:
    """Create an event in the named calendar. Returns the new uid + summary.

    Args:
        title: event summary.
        start, end: ISO8601 datetimes (timezone-aware preferred; naive = UTC).
        calendar: display name or url-tail of the target calendar.
        description: optional long body.
        location: optional location string.
        rrule: optional RFC5545 RRULE (e.g. "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO").
    """
    client = ensure_client()
    handle = client.find(calendar)
    if not handle.writable:
        raise ValueError(f"calendar {handle.name!r} is read-only (no VEVENT support)")
    event = Event(
        uid=new_uid(),
        title=title,
        start=parse_iso(start),
        end=parse_iso(end),
        description=description,
        location=location,
        rrule=rrule,
        calendar=handle.name,
    )
    blob = build_vcal(event)
    handle._cal.save_event(blob.decode("utf-8"))
    return event.to_dict()
