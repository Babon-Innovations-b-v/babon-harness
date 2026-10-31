"""A title the assistant writes never carries an HTML entity.

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
"""
from __future__ import annotations

from apps.assistant.core import meeting_reminders
from apps.assistant.core.tools.agenda import caldav, create_video_call, talk

_STORED = "\r\n".join([
    "BEGIN:VCALENDAR", "VERSION:2.0", "BEGIN:VEVENT", "UID:assistant-f9eac58b80f5bf72",
    "DTSTART:20261019T100000Z", "DTEND:20261019T120000Z", "SUMMARY:Alex and Robin",
    "END:VEVENT", "END:VCALENDAR", "",
])


def _summary_lines(ics: str) -> list[str]:
    return [line for line in ics.splitlines() if line.startswith("SUMMARY")]


def test_an_added_meeting_stores_the_ampersand_not_the_entity() -> None:
    ics = caldav.build_event("assistant-x", "Alex &amp; Sam", "20261019T080000Z", "20261019T090000Z").decode()
    assert _summary_lines(ics) == ["SUMMARY:Alex & Sam"], "an added title kept the HTML entity"


def test_an_updated_title_stores_the_ampersand_not_the_entity() -> None:
    ics = caldav.splice_properties(_STORED, {"SUMMARY": "Alex &amp; Robin"}).decode()
    assert _summary_lines(ics) == ["SUMMARY:Alex & Robin"], "an updated title kept the HTML entity"


def test_a_title_already_stored_with_the_entity_is_read_out_plainly() -> None:
    assert meeting_reminders._display("Alex &amp\\; Sam", "en") == "Alex & Sam"


def test_a_call_room_is_named_with_the_ampersand(tmp_path, monkeypatch) -> None:
    named: list[str] = []
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.setenv("ASSISTANT_VIDEO_CALL", "1")
    monkeypatch.setattr(talk, "create_call_room", lambda topic: named.append(topic) or "https://cloud.example.org/call/abc")
    monkeypatch.setattr(talk, "invite_users", lambda link, names: [])
    create_video_call.execute({"topic": "Alex &amp; Robin"})
    assert named == ["Alex & Robin"], "the Talk room was named with the HTML entity"
