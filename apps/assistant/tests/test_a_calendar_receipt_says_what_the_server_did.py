"""A calendar receipt says what the server did: a refused write is never
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
"""
from __future__ import annotations

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


def test_a_move_of_assistants_own_icloud_event_quotes_its_real_etag_and_lands(icloud) -> None:
    answer = agenda_act.execute(_move_to_eleven(), actor="Alex")
    assert answer.startswith("moved "), answer
    assert icloud.puts == [(f"{WORK}{OWN_EVENT}.ics", ETAG)], icloud.puts


def test_a_refused_write_on_an_event_that_is_still_there_never_says_it_was_removed(icloud_without_multiget) -> None:
    answer = agenda_act.execute(_move_to_eleven(), actor="Alex")
    assert "removed" not in answer, answer
    assert "still there" in answer, answer
    assert not answer.startswith("moved "), "a refused move must not read as a landed one"


def _weekly_monday_add(**extra) -> dict:
    return {"action": "add", "calendar": "alex", "summary": "Alex & Sam weekly",
            "start": "2026-09-07 10:00", "end": "2026-09-07 10:30",
            "rrule": "FREQ=WEEKLY;BYDAY=MO;UNTIL=20261012T235959Z", **extra}


def test_a_repeating_add_refuses_a_clash_on_its_third_monday(icloud) -> None:
    icloud.resources[f"{WORK}dentist.ics"] = caldav.build_event(
        "dentist", "Tandarts", "20260921T080000Z", "20260921T090000Z").decode()
    before = len(icloud.puts)
    answer = agenda_act.execute(_weekly_monday_add(), actor="Alex")
    assert answer.startswith("not booked:"), answer
    assert "21 Sep" in answer, f"the clashing Monday is not named: {answer}"
    assert len(icloud.puts) == before, "the series was written over a clash"


def test_a_clean_repeating_add_says_how_far_it_checked(icloud) -> None:
    answer = agenda_act.execute(_weekly_monday_add(), actor="Alex")
    assert answer.startswith("added to Work"), answer
    assert "all 6 occurrences up to Mon 12 Oct" in answer, answer
