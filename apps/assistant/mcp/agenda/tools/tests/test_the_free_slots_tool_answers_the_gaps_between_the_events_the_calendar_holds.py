"""The free slots tool answers the gaps between the events the calendar holds.

WHAT IT PINS. The agenda's tool surface, `tools.find_free_slots`: it lists the
events in the asked window from the calendar it is pointed at (one calendar by
name, or all of them), skips a VEVENT it cannot read rather than failing the
whole answer, and returns the free blocks of at least the asked minutes as
ISO strings in UTC. The CalDAV client is a made-up account of two calendars
whose searches answer saved calendar text.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The events are
made up and placed by hand on one day, window 09:00 to 13:00 UTC: Team holds
10:00-11:00, Private holds 11:30-12:00 and one unreadable entry. Asked for 30
minutes across both calendars the gaps are 09:00-10:00, 11:00-11:30 and
12:00-13:00; asked of Team alone, 09:00-10:00 and 11:00-13:00.

ONE FUNCTION. This module's one test. A new check is a parametrized case of
it, never a second function.

WHAT IT WAS PROVED AGAINST. The break in this test's register row reads the
minutes as hours, so no gap is ever long enough.

GUARDS. One test per module (#1210), 2026-11-05.
"""
from __future__ import annotations

import importlib
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from apps.assistant.mcp.agenda.ical import Event, build_vcal

list_module = importlib.import_module("apps.assistant.mcp.agenda.tools.list_events")
free_module = importlib.import_module("apps.assistant.mcp.agenda.tools.find_free_slots")


def _vcal(uid: str, start: int, start_minute: int, end: int, end_minute: int) -> str:
    return build_vcal(Event(uid, uid, datetime(2026, 5, 4, start, start_minute, tzinfo=timezone.utc),
                            datetime(2026, 5, 4, end, end_minute, tzinfo=timezone.utc)))


class _Calendar:
    def __init__(self, name: str, texts: list[str]) -> None:
        self.name, self._cal, self.texts = name, self, texts

    def search(self, **_window) -> list[SimpleNamespace]:
        return [SimpleNamespace(data=text) for text in self.texts]


class _Account:
    def __init__(self) -> None:
        self.team = _Calendar("Team", [_vcal("standup", 10, 0, 11, 0)])
        self.private = _Calendar("Private", [_vcal("dentist", 11, 30, 12, 0), "BEGIN:VCALENDAR\nnot a calendar"])

    def calendars(self) -> list[_Calendar]:
        return [self.team, self.private]

    def find(self, name: str) -> _Calendar:
        return {"Team": self.team, "Private": self.private}[name]


def _utc(hour: int, minute: int = 0) -> str:
    return datetime(2026, 5, 4, hour, minute, tzinfo=timezone.utc).isoformat()


CASES = [
    pytest.param(None, 30, [(_utc(9), _utc(10)), (_utc(11), _utc(11, 30)), (_utc(12), _utc(13))],
                 id="across-every-calendar"),
    pytest.param("Team", 30, [(_utc(9), _utc(10)), (_utc(11), _utc(13))], id="one-calendar-by-name"),
    pytest.param(None, 61, [], id="no-gap-is-longer-than-an-hour"),
]


@pytest.mark.parametrize("calendar, minutes, expected", CASES)
def test_the_free_slots_tool_answers_the_gaps_between_the_events_the_calendar_holds(
        calendar: str | None, minutes: int, expected: list, monkeypatch: pytest.MonkeyPatch) -> None:
    """The (start, end) pairs the tool answers are the gaps placed by hand."""
    monkeypatch.setattr(list_module, "ensure_client", _Account)
    slots = free_module.find_free_slots(_utc(9), _utc(13), minutes, calendar=calendar)
    assert [(slot["start"], slot["end"]) for slot in slots] == expected
