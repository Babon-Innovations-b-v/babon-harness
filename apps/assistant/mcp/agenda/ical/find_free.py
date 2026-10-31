"""find_free(), free-slot maths over a list of events.

Pure interval arithmetic; no calendar I/O (fetching the events is the
``find_free_slots`` tool's job). FreeSlot is the return shape and rides
with the callable.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .iso import iso
from .utc import utc
from .event import Event


@dataclass
class FreeSlot:
    start: datetime
    end: datetime

    def to_dict(self) -> dict:
        return {"start": iso(self.start), "end": iso(self.end)}


def find_free(events: list[Event], window_start: datetime, window_end: datetime, duration: timedelta) -> list[FreeSlot]:
    """Return blocks of free time of at least ``duration`` between events.

    Events may overlap; we merge their intervals first, then walk the
    window. Anything outside the merged-busy set that is longer than
    ``duration`` becomes a slot. Caller is expected to filter to working
    hours upstream, this helper is timezone-agnostic.
    """
    busy = sorted([(utc(ev.start), utc(ev.end)) for ev in events])
    merged: list[tuple[datetime, datetime]] = []
    for start, end in busy:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    window_start = utc(window_start)
    window_end = utc(window_end)
    slots: list[FreeSlot] = []
    cursor = window_start
    for start, end in merged:
        if start > window_end:
            break
        if end < cursor:
            continue
        if start > cursor and start - cursor >= duration:
            slots.append(FreeSlot(start=cursor, end=start))
        cursor = max(cursor, end)
    if cursor < window_end and window_end - cursor >= duration:
        slots.append(FreeSlot(start=cursor, end=window_end))
    return slots
