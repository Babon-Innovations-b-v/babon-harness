"""An event the agenda tools create is listed back with every field it was given.

WHAT IT PINS. How the two modules of the agenda server fit: `tools` takes a
person's words, `ical` turns them into the calendar's text and back. The seam
is the two public tools, `create_event` and `list_events`, with the CalDAV
client replaced by one in-memory calendar that keeps what is saved and hands it
back on a search, so nothing leaves the box.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The event is
made up here, its times written in the pinned zone's summer offset (+02:00),
and each expected field is worked out by hand: the times as the same instants
in UTC, every other field exactly as given, the calendar as the fake's name.

ONE FUNCTION. This group's one test. A new check is a parametrized case of it,
never a second function.

WHAT IT WAS PROVED AGAINST. The break in this test's register row drops the
location when the calendar text is built, so the location case fails.

GUARDS. One test per module group (#1210), 2026-11-04.
"""
from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

# By path, because the package re-exports each tool function under its module's name.
create_module = importlib.import_module("apps.assistant.mcp.agenda.tools.create_event")
list_module = importlib.import_module("apps.assistant.mcp.agenda.tools.list_events")

GIVEN = {
    "title": "Planning with the board",
    "start": "2026-05-04T09:00:00+02:00",
    "end": "2026-05-04T10:30:00+02:00",
    "calendar": "Team",
    "description": "Quarter plan, first draft",
    "location": "Room 2",
    "rrule": "FREQ=WEEKLY;INTERVAL=2",
}

CASES = [
    pytest.param("title", "Planning with the board", id="title"),
    pytest.param("start", "2026-05-04T07:00:00+00:00", id="start-in-utc"),
    pytest.param("end", "2026-05-04T08:30:00+00:00", id="end-in-utc"),
    pytest.param("description", "Quarter plan, first draft", id="description"),
    pytest.param("location", "Room 2", id="location"),
    pytest.param("rrule", "FREQ=WEEKLY;INTERVAL=2", id="repeat-rule"),
    pytest.param("calendar", "Team", id="calendar"),
]


class _OneCalendar:
    """A writable calendar that hands back, on any search, what was saved to it."""

    def __init__(self) -> None:
        self.name, self.writable, self._cal = "Team", True, self
        self.saved: list[str] = []

    def find(self, name: str) -> "_OneCalendar":
        assert name == self.name, f"the tools asked for calendar {name!r}"
        return self

    def calendars(self) -> list["_OneCalendar"]:
        return [self]

    def save_event(self, text: str) -> None:
        self.saved.append(text)

    def search(self, **_window) -> list[SimpleNamespace]:
        return [SimpleNamespace(data=text) for text in self.saved]


@pytest.mark.parametrize("field, expected", CASES)
def test_an_event_the_agenda_tools_create_is_listed_back_with_every_field_it_was_given(
        field: str, expected: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The created event, listed back over the same window, holds the hand-derived value of this field."""
    calendar = _OneCalendar()
    monkeypatch.setattr(create_module, "ensure_client", lambda: calendar)
    monkeypatch.setattr(list_module, "ensure_client", lambda: calendar)

    created = create_module.create_event(**GIVEN)
    listed = list_module.list_events(calendar="Team", start="2026-05-04T00:00:00+00:00",
                                     end="2026-05-05T00:00:00+00:00")

    assert [event["uid"] for event in listed] == [created["uid"]]
    assert listed[0][field] == expected
