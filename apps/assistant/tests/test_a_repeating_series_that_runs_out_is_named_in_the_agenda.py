"""A repeating series that runs out is named in the agenda.

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
"""
from __future__ import annotations

import re

from apps.assistant.core.tools.agenda import agenda_view


class FakeNextcloud:
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


def test_a_series_that_ended_before_the_window_is_named() -> None:
    calendar = FakeNextcloud(
        "FREQ=WEEKLY;BYDAY=MO;UNTIL=20261012T080000Z", "20260921T080000Z",
        ("20260921T080000Z", "20261012T090000Z"),
    )
    answer = agenda_view._one_calendar(calendar, "20261016T100300Z", "20261021T100300Z")
    lines = _series_lines(answer)
    assert len(lines) == 1, f"the ended series is not named: {answer!r}"
    assert "Alex & Sam" in lines[0] and "Mon 12 Oct" in lines[0]


def test_a_series_ending_soon_is_named_in_the_many_calendar_answer() -> None:
    calendar = FakeNextcloud(
        "FREQ=WEEKLY;BYDAY=MO;COUNT=13", "20261019T080000Z",
        ("20261019T080000Z", "20270111T090000Z"),
    )
    answer = agenda_view._many_calendars([calendar], "20270101T100000Z", "20270106T100000Z")
    lines = _series_lines(answer)
    assert len(lines) == 1, f"the ending series is not named: {answer!r}"
    assert "Mon 11 Jan" in lines[0]
    assert "Mon 04 Jan" in answer, "the occurrence inside the window went missing"


def test_a_series_that_never_ends_is_not_named() -> None:
    calendar = FakeNextcloud(
        "FREQ=WEEKLY;BYDAY=MO", "20261019T080000Z", ("20261019T080000Z", "99991231T000000Z"),
    )
    answer = agenda_view._one_calendar(calendar, "20270101T100000Z", "20270106T100000Z")
    assert _series_lines(answer) == []


def test_a_series_replaced_by_one_with_the_same_title_is_not_named() -> None:
    calendar = FakeNextcloud(
        "FREQ=WEEKLY;BYDAY=MO;UNTIL=20261012T080000Z", "20260921T080000Z",
        ("20260921T080000Z", "20261012T090000Z"),
    )
    calendar.add(
        "FREQ=WEEKLY;BYDAY=MO;COUNT=13", "20261019T080000Z",
        ("20261019T080000Z", "20270111T090000Z"), uid="assistant-b841f2777bee0f8e",
    )
    answer = agenda_view._one_calendar(calendar, "20261023T100000Z", "20261024T100000Z")
    assert _series_lines(answer) == [], f"a replaced series is named as ended: {answer!r}"
