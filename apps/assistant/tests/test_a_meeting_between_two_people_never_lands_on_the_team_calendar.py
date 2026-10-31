"""A meeting between two people never lands on the team calendar, and one call
reminds each person once however many calendars carry it.

WHAT IT PINS. Three seams of `apps/assistant` that put a two-person call
in front of people who were not in it:
- `agenda_act.execute`: an add names its calendar (there is no default), and
  the team calendar takes an add only as a declared whole-team event;
- `meeting_reminders.send_due_reminders`: the once-only claim is per call and
  start, not per calendar resource;
- `principles.render`: the seed doctrine no longer sends every meeting with
  other people to the team calendar.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From the
failure it prevents: a call between two people written to one person's own
calendar AND the team calendar, two resources with two UIDs, the same video
link and the same start, so two reminders. The rule decides each case by hand: a two-person add on 'team' must not reach
the server, an add on a person's calendar must, and one call is one reminder.
The calendar server is a dictionary standing in for CalDAV at
`caldav.dav_request`, the outermost seam; the Signal send is a list.
"""
from __future__ import annotations

import datetime as _dt
import re

import pytest

from apps.assistant.core import meeting_reminders, principles
from apps.assistant.core.tools.agenda import agenda_act, caldav, calendars

ALEX_PHONE = "+15550100001"
SAM_PHONE = "+15550100015"
PEOPLE = (
    f"uuid:alex-uuid=Alex:dev:{ALEX_PHONE},"
    f"uuid:sam-uuid=Sam:dev:{SAM_PHONE}"
)
WORK = "https://p00-caldav.icloud.com/123/calendars/work/"
CALL = "https://cloud.example.org/call/r4nd0mtk"


class FakeCalendarServer:
    """CalDAV as a dictionary of resource URL -> iCalendar text."""

    def __init__(self) -> None:
        self.resources: dict[str, str] = {}
        self.puts: list[str] = []

    def __call__(self, method, url, auth, body=b"", headers=None, _hop=0, _retry=0):
        if method == "PUT":
            self.puts.append(url)
            self.resources[url] = body.decode()
            return 201, ""
        if method == "GET":
            return (200, self.resources[url]) if url in self.resources else (404, "")
        if method == "REPORT":
            responses = "".join(
                f"<d:response><d:href>{href}</d:href><d:propstat><d:prop>"
                f"<d:getetag>\"1\"</d:getetag><c:calendar-data>"
                f"{text.replace('&', '&amp;').replace('<', '&lt;')}</c:calendar-data>"
                f"</d:prop></d:propstat></d:response>"
                for href, text in self.resources.items()
                if href.startswith(url)
            )
            return 207, f'<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">{responses}</d:multistatus>'
        return 405, ""


@pytest.fixture()
def server(tmp_path, monkeypatch) -> FakeCalendarServer:
    fake = FakeCalendarServer()
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.setenv("ASSISTANT_AGENDA_WRITE", "1")
    monkeypatch.setenv("AGENDA_APP_PASSWORD", "token")
    monkeypatch.setenv("AGENDA_USER", "assistant")
    monkeypatch.setenv("TEAM_CALENDAR", "team")
    monkeypatch.setenv("AGENDA_CALENDARS", f"alex=icloud|{WORK}|Work")
    monkeypatch.delenv("AGENDA_SCOPES", raising=False)
    monkeypatch.setenv("SIGNAL_PEOPLE", PEOPLE)
    monkeypatch.setattr(caldav, "dav_request", fake)
    return fake


def _team_url() -> str:
    return calendars.calendars()[calendars.TEAM_KEY].url


def _call_between_alex_and_sam(**extra) -> dict:
    return {"action": "add", "summary": "Alex & Sam", "start": "2026-09-02 10:00",
            "end": "2026-09-02 10:30", "location": CALL, **extra}


def test_an_add_that_names_no_calendar_is_refused_and_writes_nothing(server) -> None:
    """The old default sent an unnamed add to the team calendar."""
    answer = agenda_act.execute(_call_between_alex_and_sam(), actor="Alex")
    assert server.puts == [], f"an add with no calendar was written: {server.puts}"
    assert "calendar" in answer and "alex" in answer, answer


def test_a_two_person_call_on_the_team_calendar_is_refused_and_names_their_own_calendars(server) -> None:
    answer = agenda_act.execute(_call_between_alex_and_sam(calendar="team"), actor="Alex")
    assert not any(url.startswith(_team_url()) for url in server.puts), (
        "a call between Alex and Sam was written to the team calendar"
    )
    assert answer.startswith("not booked:"), answer
    assert "alex" in answer, "the refusal must name the calendars it does belong on"


def test_a_declared_team_event_and_a_personal_add_both_land(server) -> None:
    team = agenda_act.execute(
        {**_call_between_alex_and_sam(calendar="team", team_event=True), "summary": "All-hands"},
        actor="Alex",
    )
    own = agenda_act.execute(_call_between_alex_and_sam(calendar="alex"), actor="Alex")
    assert team.startswith("added to team calendar"), team
    assert own.startswith("added to Work"), own
    assert sum(url.startswith(_team_url()) for url in server.puts) == 1
    assert sum(url.startswith(WORK) for url in server.puts) == 1


def _event(uid: str, start: _dt.datetime) -> str:
    return caldav.build_event(
        uid, "Alex & Sam", start.strftime("%Y%m%dT%H%M%SZ"),
        (start + _dt.timedelta(minutes=30)).strftime("%Y%m%dT%H%M%SZ"), CALL,
    ).decode()


def test_one_call_on_two_calendars_reminds_alex_once(server, monkeypatch) -> None:
    """A Work copy and a team calendar copy of one call, two UIDs."""
    monkeypatch.setenv("ASSISTANT_MEETING_REMINDERS", "1")
    start = (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(minutes=15)).replace(second=0, microsecond=0)
    server.resources[f"{WORK}assistant-80e02a1d.ics"] = _event("assistant-80e02a1d", start)
    server.resources[f"{_team_url()}assistant-f4ef5aa0.ics"] = _event("assistant-f4ef5aa0", start)
    sent: list[str] = []
    monkeypatch.setattr(
        meeting_reminders._signal, "send",
        lambda subject, body, recipient: sent.append(recipient) or True,
    )
    meeting_reminders.send_due_reminders()
    assert sent.count(ALEX_PHONE) == 1, f"Alex was reminded {sent.count(ALEX_PHONE)} times about one call"


def test_the_seed_doctrine_does_not_send_a_meeting_with_others_to_the_team_calendar(server) -> None:
    sentences = re.split(r"(?<=[.;])\s+", principles.render(grounding=False))
    arranging = [sentence for sentence in sentences if "involving other people" in sentence]
    assert arranging, "the seed no longer says how to arrange a meeting with other people"
    assert all("team calendar" not in sentence for sentence in arranging), arranging
    assert any("own calendar" in sentence for sentence in arranging), arranging
