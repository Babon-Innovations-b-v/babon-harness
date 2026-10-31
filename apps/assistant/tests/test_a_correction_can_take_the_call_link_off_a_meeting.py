"""A correction can take the call link off a meeting, and then nobody is
reminded with it.

WHAT IT PINS. `agenda_act.execute` update in `apps/assistant`, through
its explicit `clear` list, and `meeting_reminders.send_due_reminders` reading
the result. When a teammate says a call with an outside party needs no
Nextcloud link, something has to remove the LOCATION, or the next reminders
still carry https://cloud.example.org/call/r4nd0mtk.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From the
calendar the update writes, which is a dictionary standing in for CalDAV at
`caldav.dav_request`, the outermost seam. Clearing the location means the
resource the server stores afterwards has no LOCATION line in its event, while
the title and the alarm somebody set are the lines they were. The reminder beat
selects only events whose LOCATION is a call link, so with the line gone there
is nothing to remind about, and the Signal send, a list here, stays empty. An
EMPTY location field is the old "leave it alone" rule, so it
must change nothing.
"""
from __future__ import annotations

import datetime as _dt

import pytest

from apps.assistant.core import meeting_reminders
from apps.assistant.core.tools.agenda import agenda_act, caldav, calendars

ALEX_PHONE = "+15550100001"
CALL = "https://cloud.example.org/call/r4nd0mtk"
UID = "assistant-weekly-sync"


class FakeNextcloud:
    """CalDAV as a dictionary of resource URL -> iCalendar text."""

    def __init__(self) -> None:
        self.resources: dict[str, str] = {}

    def __call__(self, method, url, auth, body=b"", headers=None, _hop=0, _retry=0):
        if method == "GET":
            return (200, self.resources[url]) if url in self.resources else (404, "")
        if method == "PUT":
            self.resources[url] = body.decode()
            return 204, ""
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


def _meeting_with_call(start: _dt.datetime) -> str:
    stamp = start.strftime("%Y%m%dT%H%M%SZ")
    finish = (start + _dt.timedelta(minutes=30)).strftime("%Y%m%dT%H%M%SZ")
    return "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "BEGIN:VEVENT", f"UID:{UID}",
        f"DTSTART:{stamp}", f"DTEND:{finish}", "SUMMARY:Call with Jordan",
        f"LOCATION:{CALL}", "BEGIN:VALARM", "ACTION:DISPLAY", "DESCRIPTION:Jordan calls",
        "TRIGGER:-PT10M", "END:VALARM", "END:VEVENT", "END:VCALENDAR", "",
    ])


@pytest.fixture()
def calendar(tmp_path, monkeypatch) -> tuple[FakeNextcloud, str]:
    fake = FakeNextcloud()
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.setenv("ASSISTANT_AGENDA_WRITE", "1")
    monkeypatch.setenv("ASSISTANT_MEETING_REMINDERS", "1")
    monkeypatch.setenv("AGENDA_APP_PASSWORD", "token")
    monkeypatch.setenv("AGENDA_USER", "assistant")
    monkeypatch.setenv("TEAM_CALENDAR", "team")
    monkeypatch.setenv("AGENDA_CALENDARS", "alex=nextcloud|alex-work|Work")
    monkeypatch.delenv("AGENDA_SCOPES", raising=False)
    monkeypatch.setenv("SIGNAL_PEOPLE", f"uuid:alex-uuid=Alex:dev:{ALEX_PHONE}")
    monkeypatch.setattr(caldav, "dav_request", fake)
    href = f"{calendars.calendars()['alex'].url}{UID}.ics"
    start = (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(minutes=15)).replace(second=0, microsecond=0)
    fake.resources[href] = _meeting_with_call(start)
    return fake, href


def _event_lines(ics_text: str) -> list[str]:
    """The master event's own property names, alarm lines left out."""
    lines = ics_text.replace("\r\n", "\n").split("\n")
    inside_alarm = False
    names = []
    for line in lines:
        if line == "BEGIN:VALARM":
            inside_alarm = True
        elif line == "END:VALARM":
            inside_alarm = False
        elif not inside_alarm and ":" in line:
            names.append(line.split(":", 1)[0].split(";", 1)[0])
    return names


def test_clearing_the_location_takes_the_call_link_off_and_nobody_is_reminded_with_it(calendar, monkeypatch) -> None:
    fake, href = calendar
    answer = agenda_act.execute({"action": "update", "calendar": "alex", "uid": UID, "clear": ["location"]}, actor="Sam")
    assert answer.startswith("updated "), answer
    stored = fake.resources[href]
    assert "LOCATION" not in _event_lines(stored), f"the call link is still on the event:\n{stored}"
    assert "SUMMARY:Call with Jordan" in stored and "DESCRIPTION:Jordan calls" in stored, (
        f"clearing the location touched other lines:\n{stored}"
    )
    sent: list[str] = []
    monkeypatch.setattr(
        meeting_reminders._signal, "send",
        lambda subject, body, recipient: sent.append(body) or True,
    )
    meeting_reminders.send_due_reminders()
    assert sent == [], f"a reminder still carried the link: {sent}"


def test_an_empty_location_still_changes_nothing(calendar) -> None:
    fake, href = calendar
    before = fake.resources[href]
    answer = agenda_act.execute({"action": "update", "calendar": "alex", "uid": UID, "location": ""}, actor="Sam")
    assert not answer.startswith("updated "), answer
    assert fake.resources[href] == before
