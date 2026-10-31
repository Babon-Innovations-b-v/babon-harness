"""A person scope whose write calendar is the team calendar is held to the
team calendar rule: a two-person add on it is refused like one on 'team'.

WHAT IT PINS. `agenda_act.execute` in `apps/assistant`: the refusal of a
non-team-event add on the team calendar is decided by the calendar the scope
writes to, not by the scope's name. An `AGENDA_SCOPES` entry such as
`robin=team|team|a teammate` (a teammate with no calendar of their own) writes to
the team calendar under another name, and a name check let the add through.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From the
configuration alone: `robin=team|team` names `team` as its write key, so its
write calendar is the team calendar's own URL, and everything there reminds every
teammate. An add on it without `team_event` must therefore
put nothing on the server, and the same add with `team_event` must land. The
calendar server is a dictionary standing in for CalDAV at
`caldav.dav_request`, the outermost seam.
"""
from __future__ import annotations

import pytest

from apps.assistant.core.tools.agenda import agenda_act, caldav, calendars

CALL = "https://cloud.example.org/call/r4nd0mtk"


class FakeCalendarServer:
    """CalDAV as a dictionary of resource URL -> iCalendar text; every
    calendar is empty, so a free/busy read finds nothing."""

    def __init__(self) -> None:
        self.puts: list[str] = []

    def __call__(self, method, url, auth, body=b"", headers=None, _hop=0, _retry=0):
        if method == "PUT":
            self.puts.append(url)
            return 201, ""
        if method == "REPORT":
            return 207, '<d:multistatus xmlns:d="DAV:"></d:multistatus>'
        return 404, ""


@pytest.fixture()
def server(tmp_path, monkeypatch) -> FakeCalendarServer:
    fake = FakeCalendarServer()
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.setenv("ASSISTANT_AGENDA_WRITE", "1")
    monkeypatch.setenv("AGENDA_APP_PASSWORD", "token")
    monkeypatch.setenv("AGENDA_USER", "assistant")
    monkeypatch.setenv("TEAM_CALENDAR", "team")
    monkeypatch.delenv("AGENDA_CALENDARS", raising=False)
    monkeypatch.setenv("AGENDA_SCOPES", "robin=team|team|Robin")
    monkeypatch.setattr(caldav, "dav_request", fake)
    return fake


def _call(**extra) -> dict:
    return {"action": "add", "calendar": "robin", "summary": "Alex & Robin",
            "start": "2026-10-07 10:00", "end": "2026-10-07 10:30", "location": CALL, **extra}


def _team_puts(server: FakeCalendarServer) -> list[str]:
    team = calendars.calendars()[calendars.TEAM_KEY].url
    return [url for url in server.puts if url.startswith(team)]


def test_a_two_person_add_on_a_scope_that_writes_to_the_team_calendar_is_refused(server) -> None:
    answer = agenda_act.execute(_call(), actor="Alex")
    assert _team_puts(server) == [], "a two-person call reached the team calendar through the 'robin' scope"
    assert answer.startswith("not booked:"), answer
    assert "robin" not in answer.split("(")[-1], "the refusal must not offer the team calendar alias as a person calendar"


def test_a_declared_team_event_on_that_scope_still_lands(server) -> None:
    answer = agenda_act.execute(_call(team_event=True), actor="Alex")
    assert len(_team_puts(server)) == 1, answer
