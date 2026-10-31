"""agenda_view never lists an event outside the window it was asked for.

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

from types import SimpleNamespace

from apps.assistant.core.tools.agenda import agenda_availability, agenda_view


class FakeICloud:
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


def test_yesterdays_birthday_is_not_in_todays_agenda() -> None:
    answer = agenda_view._one_calendar(FakeICloud("20261022"), "20261023T060006Z", "20261024T060006Z")
    assert answer.startswith("No "), f"an event outside the window was listed: {answer!r}"
    assert "22 Oct" not in answer


def test_the_birthday_is_in_its_own_days_agenda() -> None:
    answer = agenda_view._one_calendar(FakeICloud("20261022"), "20261022T060009Z", "20261023T060009Z")
    assert "Thu 22 Oct, all day: Birthday" in answer, answer


def test_a_birthday_first_written_last_year_still_shows_this_year() -> None:
    answer = agenda_view._many_calendars([FakeICloud("20251022")], "20261022T060009Z", "20261023T060009Z")
    assert "Thu 22 Oct, all day: Birthday" in answer, answer


def test_yesterdays_birthday_does_not_make_anyone_busy_today() -> None:
    scope = SimpleNamespace(read=[FakeICloud("20261022")])
    events, errors = agenda_availability.busy_in_window(scope, "20261023T080000Z", "20261023T090000Z")
    assert (events, errors) == ([], [])
