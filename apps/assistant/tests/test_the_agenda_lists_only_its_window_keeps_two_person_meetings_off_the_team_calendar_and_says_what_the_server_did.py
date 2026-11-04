"""The agenda lists only the window asked for, names a series that runs out, keeps a meeting between two people off the team calendar, writes plain titles, can take a call link off, and says what the server did.

Every check below is one row of CASES under the one test function; a
row that fails fails the test. The sections below are the notes each
check was written with.

A calendar receipt says what the server did: a refused write is never
reported as a removed event, and a repeating add is checked, or says it was not,
beyond its first occurrence.

WHAT IT PINS. `agenda_act.execute` in `apps/assistant` (finding
15), at the three places a receipt used to say more than the server had told it:
- a move of the assistant's own event on iCloud quotes the event's real etag, so the
  conditional write lands instead of being refused;
- when a write sent with `If-Match: *` is refused (412) anyway, the event is
  read again before anything is said, and an event still there is reported as
  still there, never as removed;
- a repeating add refuses a clash on a LATER occurrence, naming that date, and
  a clean series says how many occurrences it checked.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From the server
in each case, which is a dictionary standing in for CalDAV at
`caldav.dav_request`, the outermost seam. It behaves the way iCloud can:
a GET of the event answers 200 and a PUT under `If-Match: *` answers 412. The
event is in the dictionary throughout, so "removed" is false by construction; a
PUT quoting the stored etag is the one the server accepts, so a move that lands
must have quoted it. For the series, the busy event sits on the third Monday of
a six-Monday rule, so the add must not reach the server and the refusal must
name that Monday.

A correction can take the call link off a meeting, and then nobody is
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

A meeting between two people never lands on the team calendar, and one call
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

A repeating series that runs out is named in the agenda.

WHAT IT PINS. `agenda_view` in `apps/assistant`, both the one-calendar
and the many-calendar answer, through `caldav.series_last_start`. When a
weekly series runs out, a window read after its last date returns nothing for
that slot, and the assistant reports the day as open without saying the series
ended. A replacement series with a COUNT lapses later in the same silent way.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. By counting on
a calendar: weekly on Monday from Mon 21 Sep 2026 until 12 Oct 08:00 UTC has its
last occurrence on Mon 12 Oct. Thirteen Mondays from Mon 19 Oct 2026 are 19 and
26 Oct, 2, 9, 16, 23 and 30 Nov, 7, 14, 21 and 28 Dec, 4 Jan and 11 Jan 2027,
so the last is Mon 11 Jan. A series with no COUNT or UNTIL never ends and must
not be named, and neither is one that a same-title series carries on past
its last date: the old series ending 12 Oct was replaced on 16 Oct by the
COUNT=13 one, which continues it. The fake server answers a time-range read the way CalDAV does:
a series is returned only when its span overlaps the range asked for.

A person scope whose write calendar is the team calendar is held to the
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

A title the assistant writes never carries an HTML entity.

WHAT IT PINS. The three places in `apps/assistant` where text the assistant
passes in a tool call becomes text people read: `caldav.build_event` (an added
meeting), `caldav.splice_properties` (an updated one), `create_video_call`
(the Talk room name, which also becomes the notulen title), and the read side
in `meeting_reminders._display` for the titles already stored that way. A
model can pass 'Alex &amp; Robin' as a summary; without this the calendar
keeps the entity and the reminders to both read "Alex &amp; Robin".

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. A calendar
title is plain text, so '&amp;' means '&'. RFC 5545 escapes only backslash,
semicolon, comma and newline in a TEXT value, so 'the owner & a teammate' is written as
the line 'SUMMARY:the owner & a teammate' with nothing escaped. The stored form
'the owner &amp\\; a teammate' is what escaping the entity would make of it.

agenda_view never lists an event outside the window it was asked for.

WHAT IT PINS. `agenda_view` and `agenda_availability.busy_in_window` in
`apps/assistant`, through `caldav.expand_all` and `caldav.in_window`.
A brief that asks a calendar for 23 Oct 06:00Z onwards can get back the
unexpanded yearly master of a birthday on 22 Oct, and print it as
"Thu 22 Oct, all day: Birthday (repeats)".

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From the
calendar: DTSTART;VALUE=DATE:20261022 with DTEND 20261023 is all of Thursday
22 Oct in local, 21 Oct 22:00Z to 22 Oct 22:00Z. A window opening at
23 Oct 06:00Z does not overlap it, and one opening at 22 Oct 06:00Z does. The
same yearly birthday first written in 2025 falls on 22 Oct 2026 as well, so
filtering by the master's own 2025 date must not lose it.
"""
from __future__ import annotations

from apps.assistant.conftest import FROZEN_AT

import inspect


# From a calendar receipt says what the server did.

import re


import pytest


from apps.assistant.core.tools.agenda import agenda_act, caldav


WORK = "https://p00-caldav.icloud.com/123/calendars/work/"


OWN_EVENT = "assistant-42f8cc30a9d95635"


ETAG = '"etag-7"'


class FakeICloud:
    """A calendar collection as a dictionary of resource URL -> iCalendar text,
    answering the way iCloud can answer."""

    def __init__(self, multiget_works: bool = True) -> None:
        self.resources: dict[str, str] = {}
        self.etags: dict[str, str] = {}
        self.puts: list[tuple[str, str]] = []
        self.multiget_works = multiget_works

    def __call__(self, method, url, auth, body=b"", headers=None, _hop=0, _retry=0):
        condition = (headers or {}).get("If-Match", "")
        if method == "GET":
            return (200, self.resources[url]) if url in self.resources else (404, "")
        if method == "PUT":
            self.puts.append((url, condition))
            if url in self.resources and condition != self.etags.get(url):
                return 412, "precondition failed"
            self.resources[url] = body.decode()
            self.etags[url] = '"etag-8"'
            return 204, ""
        if method == "REPORT" and b"calendar-multiget" in body:
            if not self.multiget_works:
                return 400, "bad request"
            return 207, self._multistatus(
                href for href in self.resources if href.endswith(re.search(rb"<D:href>(.*?)</D:href>", body).group(1).decode()))
        if method == "REPORT":
            window = re.search(rb'start="(\w+)" end="(\w+)"', body)
            low, high = caldav.parse_dt(window.group(1).decode()), caldav.parse_dt(window.group(2).decode())
            return 207, self._multistatus(href for href, text in self.resources.items() if self._inside(text, low, high))
        return 405, ""

    @staticmethod
    def _inside(text: str, low, high) -> bool:
        start, end = caldav.event_span(caldav.parse_events(text)[0])
        return start < high and low < end

    def _multistatus(self, hrefs) -> str:
        responses = "".join(
            f"<d:response><d:href>{href}</d:href><d:propstat><d:prop>"
            f"<d:getetag>{self.etags.get(href, '')}</d:getetag><c:calendar-data>"
            f"{self.resources[href].replace('&', '&amp;').replace('<', '&lt;')}</c:calendar-data>"
            f"</d:prop></d:propstat></d:response>"
            for href in hrefs
        )
        return f'<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">{responses}</d:multistatus>'


def _install(monkeypatch, tmp_path, fake: FakeICloud) -> FakeICloud:
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.setenv("ASSISTANT_AGENDA_WRITE", "1")
    monkeypatch.setenv("AGENDA_APP_PASSWORD", "token")
    monkeypatch.setenv("AGENDA_USER", "assistant")
    monkeypatch.setenv("TEAM_CALENDAR", "team")
    monkeypatch.setenv("AGENDA_CALENDARS", f"alex=icloud|{WORK}|Work")
    monkeypatch.delenv("AGENDA_SCOPES", raising=False)
    monkeypatch.setattr(caldav, "dav_request", fake)
    return fake


def _with_own_event(fake: FakeICloud) -> FakeICloud:
    href = f"{WORK}{OWN_EVENT}.ics"
    fake.resources[href] = caldav.build_event(
        OWN_EVENT, "Alex & Sam", "20260831T080000Z", "20260831T083000Z").decode()
    fake.etags[href] = ETAG
    return fake


@pytest.fixture()
def icloud(tmp_path, monkeypatch) -> FakeICloud:
    return _install(monkeypatch, tmp_path, _with_own_event(FakeICloud()))


@pytest.fixture()
def icloud_without_multiget(tmp_path, monkeypatch) -> FakeICloud:
    return _install(monkeypatch, tmp_path, _with_own_event(FakeICloud(multiget_works=False)))


def _move_to_eleven() -> dict:
    return {"action": "move", "calendar": "alex", "uid": OWN_EVENT,
            "start": "2026-08-31 11:00", "end": "2026-08-31 11:30"}


def _a_move_of_assistants_own_icloud_event_quotes_its_real_etag_and_lands(icloud) -> None:
    answer = agenda_act.execute(_move_to_eleven(), actor="Alex")
    assert answer.startswith("moved "), answer
    assert icloud.puts == [(f"{WORK}{OWN_EVENT}.ics", ETAG)], icloud.puts


def _a_refused_write_on_an_event_that_is_still_there_never_says_it_was_removed(icloud_without_multiget) -> None:
    answer = agenda_act.execute(_move_to_eleven(), actor="Alex")
    assert "removed" not in answer, answer
    assert "still there" in answer, answer
    assert not answer.startswith("moved "), "a refused move must not read as a landed one"


def _weekly_monday_add(**extra) -> dict:
    return {"action": "add", "calendar": "alex", "summary": "Alex & Sam weekly",
            "start": "2026-09-07 10:00", "end": "2026-09-07 10:30",
            "rrule": "FREQ=WEEKLY;BYDAY=MO;UNTIL=20261012T235959Z", **extra}


def _a_repeating_add_refuses_a_clash_on_its_third_monday(icloud) -> None:
    icloud.resources[f"{WORK}dentist.ics"] = caldav.build_event(
        "dentist", "Tandarts", "20260921T080000Z", "20260921T090000Z").decode()
    before = len(icloud.puts)
    answer = agenda_act.execute(_weekly_monday_add(), actor="Alex")
    assert answer.startswith("not booked:"), answer
    assert "21 Sep" in answer, f"the clashing Monday is not named: {answer}"
    assert len(icloud.puts) == before, "the series was written over a clash"


def _a_clean_repeating_add_says_how_far_it_checked(icloud) -> None:
    answer = agenda_act.execute(_weekly_monday_add(), actor="Alex")
    assert answer.startswith("added to Work"), answer
    assert "all 6 occurrences up to Mon 12 Oct" in answer, answer

# From a correction can take the call link off a meeting.

import datetime as _dt


from apps.assistant.core import meeting_reminders


from apps.assistant.core.tools.agenda import calendars


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
    start = (FROZEN_AT + _dt.timedelta(minutes=15)).replace(second=0, microsecond=0)
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


def _clearing_the_location_takes_the_call_link_off_and_nobody_is_reminded_with_it(calendar, monkeypatch) -> None:
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


def _an_empty_location_still_changes_nothing(calendar) -> None:
    fake, href = calendar
    before = fake.resources[href]
    answer = agenda_act.execute({"action": "update", "calendar": "alex", "uid": UID, "location": ""}, actor="Sam")
    assert not answer.startswith("updated "), answer
    assert fake.resources[href] == before

# From a meeting between two people never lands on the team calendar.

from apps.assistant.core import principles


SAM_PHONE = "+15550100015"


PEOPLE = (
    f"uuid:alex-uuid=Alex:dev:{ALEX_PHONE},"
    f"uuid:sam-uuid=Sam:dev:{SAM_PHONE}"
)


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


def _an_add_that_names_no_calendar_is_refused_and_writes_nothing(server) -> None:
    """The old default sent an unnamed add to the team calendar."""
    answer = agenda_act.execute(_call_between_alex_and_sam(), actor="Alex")
    assert server.puts == [], f"an add with no calendar was written: {server.puts}"
    assert "calendar" in answer and "alex" in answer, answer


def _a_two_person_call_on_the_team_calendar_is_refused_and_names_their_own_calendars(server) -> None:
    answer = agenda_act.execute(_call_between_alex_and_sam(calendar="team"), actor="Alex")
    assert not any(url.startswith(_team_url()) for url in server.puts), (
        "a call between Alex and Sam was written to the team calendar"
    )
    assert answer.startswith("not booked:"), answer
    assert "alex" in answer, "the refusal must name the calendars it does belong on"


def _a_declared_team_event_and_a_personal_add_both_land(server) -> None:
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


def _one_call_on_two_calendars_reminds_alex_once(server, monkeypatch) -> None:
    """A Work copy and a team calendar copy of one call, two UIDs."""
    monkeypatch.setenv("ASSISTANT_MEETING_REMINDERS", "1")
    start = (FROZEN_AT + _dt.timedelta(minutes=15)).replace(second=0, microsecond=0)
    server.resources[f"{WORK}assistant-80e02a1d.ics"] = _event("assistant-80e02a1d", start)
    server.resources[f"{_team_url()}assistant-f4ef5aa0.ics"] = _event("assistant-f4ef5aa0", start)
    sent: list[str] = []
    monkeypatch.setattr(
        meeting_reminders._signal, "send",
        lambda subject, body, recipient: sent.append(recipient) or True,
    )
    meeting_reminders.send_due_reminders()
    assert sent.count(ALEX_PHONE) == 1, f"Alex was reminded {sent.count(ALEX_PHONE)} times about one call"


def _the_seed_doctrine_does_not_send_a_meeting_with_others_to_the_team_calendar(server) -> None:
    sentences = re.split(r"(?<=[.;])\s+", principles.render(grounding=False))
    arranging = [sentence for sentence in sentences if "involving other people" in sentence]
    assert arranging, "the seed no longer says how to arrange a meeting with other people"
    assert all("team calendar" not in sentence for sentence in arranging), arranging
    assert any("own calendar" in sentence for sentence in arranging), arranging

# From a repeating series that runs out is named in the agenda.

from apps.assistant.core.tools.agenda import agenda_view


class FakeNextcloud_4:
    """One calendar holding series masters, answering time-range REPORTs."""

    display = "Alex werk"
    url = "https://cloud.example.org/remote.php/dav/calendars/assistant/alex/"

    def __init__(self, rrule: str, dtstart: str, span: tuple[str, str], uid: str = "assistant-71312fe75497f190") -> None:
        self.masters = [(self._ics(uid, rrule, dtstart), span)]

    def add(self, rrule: str, dtstart: str, span: tuple[str, str], uid: str) -> None:
        self.masters.append((self._ics(uid, rrule, dtstart), span))

    @staticmethod
    def _ics(uid: str, rrule: str, dtstart: str) -> str:
        return "\r\n".join([
            "BEGIN:VCALENDAR", "VERSION:2.0", "BEGIN:VEVENT", f"UID:{uid}",
            f"DTSTART:{dtstart}", f"DTEND:{dtstart[:9]}090000Z", "SUMMARY:Alex & Sam",
            f"RRULE:{rrule}", "END:VEVENT", "END:VCALENDAR", "",
        ])

    def request(self, method, subpath="", body=b"", headers=None):
        asked_from, asked_to = re.search(rb'time-range start="(\w+)" end="(\w+)"', body).groups()
        responses = ""
        for index, (ics, span) in enumerate(self.masters):
            if asked_from.decode() < span[1] and asked_to.decode() > span[0]:
                data = ics.replace("&", "&amp;")
                responses += f"<d:response><d:href>{self.url}{index}.ics</d:href><c:calendar-data>{data}</c:calendar-data></d:response>"
        return 207, f'<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">{responses}</d:multistatus>'


def _series_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if "Series ending" in line]


def _a_series_that_ended_before_the_window_is_named() -> None:
    calendar = FakeNextcloud_4(
        "FREQ=WEEKLY;BYDAY=MO;UNTIL=20261012T080000Z", "20260921T080000Z",
        ("20260921T080000Z", "20261012T090000Z"),
    )
    answer = agenda_view._one_calendar(calendar, "20261016T100300Z", "20261021T100300Z")
    lines = _series_lines(answer)
    assert len(lines) == 1, f"the ended series is not named: {answer!r}"
    assert "Alex & Sam" in lines[0] and "Mon 12 Oct" in lines[0]


def _a_series_ending_soon_is_named_in_the_many_calendar_answer() -> None:
    calendar = FakeNextcloud_4(
        "FREQ=WEEKLY;BYDAY=MO;COUNT=13", "20261019T080000Z",
        ("20261019T080000Z", "20270111T090000Z"),
    )
    answer = agenda_view._many_calendars([calendar], "20270101T100000Z", "20270106T100000Z")
    lines = _series_lines(answer)
    assert len(lines) == 1, f"the ending series is not named: {answer!r}"
    assert "Mon 11 Jan" in lines[0]
    assert "Mon 04 Jan" in answer, "the occurrence inside the window went missing"


def _a_series_that_never_ends_is_not_named() -> None:
    calendar = FakeNextcloud_4(
        "FREQ=WEEKLY;BYDAY=MO", "20261019T080000Z", ("20261019T080000Z", "99991231T000000Z"),
    )
    answer = agenda_view._one_calendar(calendar, "20270101T100000Z", "20270106T100000Z")
    assert _series_lines(answer) == []


def _a_series_replaced_by_one_with_the_same_title_is_not_named() -> None:
    calendar = FakeNextcloud_4(
        "FREQ=WEEKLY;BYDAY=MO;UNTIL=20261012T080000Z", "20260921T080000Z",
        ("20260921T080000Z", "20261012T090000Z"),
    )
    calendar.add(
        "FREQ=WEEKLY;BYDAY=MO;COUNT=13", "20261019T080000Z",
        ("20261019T080000Z", "20270111T090000Z"), uid="assistant-b841f2777bee0f8e",
    )
    answer = agenda_view._one_calendar(calendar, "20261023T100000Z", "20261024T100000Z")
    assert _series_lines(answer) == [], f"a replaced series is named as ended: {answer!r}"

# From a scope that writes to the team calendar is held to the team calendar rule.

class FakeCalendarServer_5:
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
def server_5(tmp_path, monkeypatch) -> FakeCalendarServer_5:
    fake = FakeCalendarServer_5()
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


def _team_puts(server_5: FakeCalendarServer_5) -> list[str]:
    team = calendars.calendars()[calendars.TEAM_KEY].url
    return [url for url in server_5.puts if url.startswith(team)]


def _a_two_person_add_on_a_scope_that_writes_to_the_team_calendar_is_refused(server_5) -> None:
    answer = agenda_act.execute(_call(), actor="Alex")
    assert _team_puts(server_5) == [], "a two-person call reached the team calendar through the 'robin' scope"
    assert answer.startswith("not booked:"), answer
    assert "robin" not in answer.split("(")[-1], "the refusal must not offer the team calendar alias as a person calendar"


def _a_declared_team_event_on_that_scope_still_lands(server_5) -> None:
    answer = agenda_act.execute(_call(team_event=True), actor="Alex")
    assert len(_team_puts(server_5)) == 1, answer

# From a title assistant writes never carries an html entity.

from apps.assistant.core.tools.agenda import create_video_call, talk


_STORED = "\r\n".join([
    "BEGIN:VCALENDAR", "VERSION:2.0", "BEGIN:VEVENT", "UID:assistant-f9eac58b80f5bf72",
    "DTSTART:20261019T100000Z", "DTEND:20261019T120000Z", "SUMMARY:Alex and Robin",
    "END:VEVENT", "END:VCALENDAR", "",
])


def _summary_lines(ics: str) -> list[str]:
    return [line for line in ics.splitlines() if line.startswith("SUMMARY")]


def _an_added_meeting_stores_the_ampersand_not_the_entity() -> None:
    ics = caldav.build_event("assistant-x", "Alex &amp; Sam", "20261019T080000Z", "20261019T090000Z").decode()
    assert _summary_lines(ics) == ["SUMMARY:Alex & Sam"], "an added title kept the HTML entity"


def _an_updated_title_stores_the_ampersand_not_the_entity() -> None:
    ics = caldav.splice_properties(_STORED, {"SUMMARY": "Alex &amp; Robin"}).decode()
    assert _summary_lines(ics) == ["SUMMARY:Alex & Robin"], "an updated title kept the HTML entity"


def _a_title_already_stored_with_the_entity_is_read_out_plainly() -> None:
    assert meeting_reminders._display("Alex &amp\\; Sam", "en") == "Alex & Sam"


def _a_call_room_is_named_with_the_ampersand(tmp_path, monkeypatch) -> None:
    named: list[str] = []
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.setenv("ASSISTANT_VIDEO_CALL", "1")
    monkeypatch.setattr(talk, "create_call_room", lambda topic: named.append(topic) or "https://cloud.example.org/call/abc")
    monkeypatch.setattr(talk, "invite_users", lambda link, names: [])
    create_video_call.execute({"topic": "Alex &amp; Robin"})
    assert named == ["Alex & Robin"], "the Talk room was named with the HTML entity"

# From agenda view never lists an event outside the window it was asked for.

from types import SimpleNamespace


from apps.assistant.core.tools.agenda import agenda_availability


class FakeICloud_7:
    """An iCloud calendar that answers every REPORT with one unexpanded master,
    the way iCloud can answer."""

    display = "Prive"
    url = "https://p42-caldav.icloud.com/123/calendars/home/"

    def __init__(self, first_day: str) -> None:
        next_day = str(int(first_day) + 1)
        self.ics = "\r\n".join([
            "BEGIN:VCALENDAR", "VERSION:2.0", "BEGIN:VEVENT",
            "UID:00000000-0000-4000-8000-000000000001",
            f"DTSTART;VALUE=DATE:{first_day}", f"DTEND;VALUE=DATE:{next_day}",
            "RRULE:FREQ=YEARLY", "SUMMARY:Birthday", "END:VEVENT", "END:VCALENDAR", "",
        ])

    def request(self, method, subpath="", body=b"", headers=None):
        return 207, (
            '<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
            f"<d:response><d:href>{self.url}x.ics</d:href>"
            f"<c:calendar-data>{self.ics}</c:calendar-data></d:response></d:multistatus>"
        )


def _yesterdays_birthday_is_not_in_todays_agenda() -> None:
    answer = agenda_view._one_calendar(FakeICloud_7("20261022"), "20261023T060006Z", "20261024T060006Z")
    assert answer.startswith("No "), f"an event outside the window was listed: {answer!r}"
    assert "22 Oct" not in answer


def _the_birthday_is_in_its_own_days_agenda() -> None:
    answer = agenda_view._one_calendar(FakeICloud_7("20261022"), "20261022T060009Z", "20261023T060009Z")
    assert "Thu 22 Oct, all day: Birthday" in answer, answer


def _a_birthday_first_written_last_year_still_shows_this_year() -> None:
    answer = agenda_view._many_calendars([FakeICloud_7("20251022")], "20261022T060009Z", "20261023T060009Z")
    assert "Thu 22 Oct, all day: Birthday" in answer, answer


def _yesterdays_birthday_does_not_make_anyone_busy_today() -> None:
    scope = SimpleNamespace(read=[FakeICloud_7("20261022")])
    events, errors = agenda_availability.busy_in_window(scope, "20261023T080000Z", "20261023T090000Z")
    assert (events, errors) == ([], [])


def _cases(scenario, argnames="", argvalues=((),), ids=None, *, marks=(), uses=()):
    """One case per row a check is given; a check given no rows is one case of its fixtures."""
    names = [name.strip() for name in argnames.split(",") if name.strip()] if isinstance(argnames, str) else list(argnames)
    rows = []
    for index, row in enumerate(argvalues):
        row_marks, row_id = (), None
        if isinstance(row, type(pytest.param())):
            row, row_marks, row_id = row.values, row.marks, row.id
        elif len(names) == 1:
            row = (row,)
        if row_id is None and isinstance(ids, (list, tuple)):
            row_id = ids[index]
        label = scenario.__name__.lstrip("_") + (f"-{row_id if row_id is not None else index}" if names else "")
        rows.append(pytest.param(scenario, dict(zip(names, row)), tuple(uses), id=label, marks=(*marks, *row_marks)))
    return rows


CASES = [
    *_cases(_a_move_of_assistants_own_icloud_event_quotes_its_real_etag_and_lands),
    *_cases(_a_refused_write_on_an_event_that_is_still_there_never_says_it_was_removed),
    *_cases(_a_repeating_add_refuses_a_clash_on_its_third_monday),
    *_cases(_a_clean_repeating_add_says_how_far_it_checked),
    *_cases(_clearing_the_location_takes_the_call_link_off_and_nobody_is_reminded_with_it),
    *_cases(_an_empty_location_still_changes_nothing),
    *_cases(_an_add_that_names_no_calendar_is_refused_and_writes_nothing),
    *_cases(_a_two_person_call_on_the_team_calendar_is_refused_and_names_their_own_calendars),
    *_cases(_a_declared_team_event_and_a_personal_add_both_land),
    *_cases(_one_call_on_two_calendars_reminds_alex_once),
    *_cases(_the_seed_doctrine_does_not_send_a_meeting_with_others_to_the_team_calendar),
    *_cases(_a_series_that_ended_before_the_window_is_named),
    *_cases(_a_series_ending_soon_is_named_in_the_many_calendar_answer),
    *_cases(_a_series_that_never_ends_is_not_named),
    *_cases(_a_series_replaced_by_one_with_the_same_title_is_not_named),
    *_cases(_a_two_person_add_on_a_scope_that_writes_to_the_team_calendar_is_refused),
    *_cases(_a_declared_team_event_on_that_scope_still_lands),
    *_cases(_an_added_meeting_stores_the_ampersand_not_the_entity),
    *_cases(_an_updated_title_stores_the_ampersand_not_the_entity),
    *_cases(_a_title_already_stored_with_the_entity_is_read_out_plainly),
    *_cases(_a_call_room_is_named_with_the_ampersand),
    *_cases(_yesterdays_birthday_is_not_in_todays_agenda),
    *_cases(_the_birthday_is_in_its_own_days_agenda),
    *_cases(_a_birthday_first_written_last_year_still_shows_this_year),
    *_cases(_yesterdays_birthday_does_not_make_anyone_busy_today),
]


@pytest.mark.parametrize("scenario, given, uses", CASES)
def test_the_agenda_lists_only_its_window_keeps_two_person_meetings_off_the_team_calendar_and_says_what_the_server_did(scenario, given, uses, request):
    """The agenda lists only the window asked for, names a series that runs out, keeps a meeting between two people off the team calendar, writes plain titles, can take a call link off, and says what the server did: every row of CASES must hold, each on the frozen clock."""
    request.getfixturevalue("frozen_clock")
    for name in uses:
        request.getfixturevalue(name)
    wanted = [name for name, parameter in inspect.signature(scenario).parameters.items()
              if name not in given and parameter.default is parameter.empty]
    scenario(**given, **{name: request.getfixturevalue(name) for name in wanted})
