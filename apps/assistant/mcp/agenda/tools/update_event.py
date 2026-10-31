"""update_event tool, field updates by uid; omitted fields are preserved."""
from __future__ import annotations

from ..ical import Event, build_vcal, parse_iso, parse_vcal
from ..runtime import ensure_client


def update_event(
    uid: str,
    calendar: str,
    title: str | None = None,
    start: str | None = None,
    end: str | None = None,
    description: str | None = None,
    location: str | None = None,
    rrule: str | None = None,
) -> dict:
    """Update fields on an existing event by uid. Omitted fields preserved."""
    client = ensure_client()
    handle = client.find(calendar)
    if not handle.writable:
        raise ValueError(f"calendar {handle.name!r} is read-only (no VEVENT support)")
    raw = client.fetch_event(calendar, uid)
    existing = parse_vcal(raw.data, calendar_name=handle.name)

    updated = Event(
        uid=existing.uid,
        title=title if title is not None else existing.title,
        start=parse_iso(start) if start else existing.start,
        end=parse_iso(end) if end else existing.end,
        description=description if description is not None else existing.description,
        location=location if location is not None else existing.location,
        rrule=rrule if rrule is not None else existing.rrule,
        calendar=handle.name,
    )
    raw.data = build_vcal(updated).decode("utf-8")
    raw.save()
    return updated.to_dict()
