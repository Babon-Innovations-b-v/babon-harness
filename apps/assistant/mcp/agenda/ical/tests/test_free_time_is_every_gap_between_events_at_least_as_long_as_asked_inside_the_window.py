"""Free time is every gap between events at least as long as asked, inside the window.

WHAT IT PINS. `ical.find_free`, the interval arithmetic behind "when are we all
free": overlapping events count as one busy stretch, a gap exactly as long as
asked is offered, a shorter one is not, an event running past the window's end
closes it, and times in another offset are compared as the same instants in
UTC.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. A made-up day,
window 09:00 to 17:00 UTC: busy 10:00-11:00 and 10:30-12:00 (one stretch,
10:00-12:00), 12:30-13:00, and 16:30-18:00 written as 18:30-20:00 at +02:00.
The gaps are read off by hand: 09:00-10:00 (60 min), 12:00-12:30 (30 min),
13:00-16:30 (210 min).

ONE FUNCTION. This module's one test. A new check is a parametrized case of
it, never a second function.

WHAT IT WAS PROVED AGAINST. The break in this test's register row offers only
gaps longer than asked, so the gap of exactly an hour is lost.

GUARDS. One test per module (#1210), 2026-11-05.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from apps.assistant.mcp.agenda.ical import Event, find_free

UTC = timezone.utc
PLUS_TWO = timezone(timedelta(hours=2))


def _at(hour: int, minute: int = 0, zone: timezone = UTC) -> datetime:
    return datetime(2026, 5, 4, hour, minute, tzinfo=zone)


DAY = [
    Event("a", "Planning", _at(10), _at(11)),
    Event("b", "Review", _at(10, 30), _at(12)),
    Event("c", "Call", _at(12, 30), _at(13)),
    Event("d", "Late", _at(18, 30, PLUS_TWO), _at(20, 0, PLUS_TWO)),
]

CASES = [
    pytest.param(DAY, 60, [("09:00", "10:00"), ("13:00", "16:30")], id="an-hour-or-more"),
    pytest.param(DAY, 30, [("09:00", "10:00"), ("12:00", "12:30"), ("13:00", "16:30")], id="half-an-hour-or-more"),
    pytest.param(DAY, 240, [], id="nothing-that-long"),
    pytest.param([], 60, [("09:00", "17:00")], id="an-empty-day-is-one-slot"),
]


@pytest.mark.parametrize("events, minutes, expected", CASES)
def test_free_time_is_every_gap_between_events_at_least_as_long_as_asked_inside_the_window(
        events: list, minutes: int, expected: list) -> None:
    """The free slots, as UTC clock times, are the gaps read off by hand."""
    slots = find_free(events, _at(9), _at(17), timedelta(minutes=minutes))
    assert [(slot.start.strftime("%H:%M"), slot.end.strftime("%H:%M")) for slot in slots] == expected
