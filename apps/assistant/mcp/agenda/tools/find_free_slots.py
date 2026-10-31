"""find_free_slots tool, free blocks of at least N minutes in a window.

Composes ``list_events`` (the fetch) with ``ical.find_free`` (the interval
maths); owns neither.
"""
from __future__ import annotations

from datetime import timedelta

from ..ical import Event, find_free, parse_iso
from .list_events import list_events


def find_free_slots(
    start: str,
    end: str,
    duration_minutes: int,
    calendar: str | None = None,
) -> list[dict]:
    """Find blocks of free time of at least ``duration_minutes`` in the window.

    Args:
        start: ISO8601 window start.
        end: ISO8601 window end.
        duration_minutes: minimum slot size to surface.
        calendar: optional restriction to one calendar; default = all.
    """
    raw_events = list_events(calendar=calendar, start=start, end=end)
    events = [
        Event(
            uid=raw["uid"],
            title=raw["title"],
            start=parse_iso(raw["start"]),
            end=parse_iso(raw["end"]),
        )
        for raw in raw_events
    ]
    slots = find_free(
        events=events,
        window_start=parse_iso(start),
        window_end=parse_iso(end),
        duration=timedelta(minutes=duration_minutes),
    )
    return [slot.to_dict() for slot in slots]
