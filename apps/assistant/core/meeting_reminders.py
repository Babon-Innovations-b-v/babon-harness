"""The 15-min-before meeting reminder, the assistant pings each attendee on Signal
with the call link just before a video meeting starts (slice 1).

This is NOT an LLM beat: it is a plain scan-and-send, like `notify_flush`.
A VM timer POSTs `/webhook/meeting-reminders` every few minutes; each run:

  1. looks a short window ahead (about 13-18 minutes) on every teammate's
     OWN calendars plus the team calendar;
  2. for each event in that window that carries a Nextcloud Talk call link
     (put there by `create_video_call` + `agenda_act` when the meeting was
     booked as a video call), sends that attendee a Signal reminder with
     the link;
  3. claims each (recipient, meeting occurrence) in `state.meeting_reminders`
     so the reminder fires EXACTLY ONCE even though the window overlaps
     across ticks and survives a pod restart.

Who gets reminded: whoever has the meeting on a calendar the assistant can see. A
one-on-one is on both attendees' own calendars (each reminded via their
own), a team ritual is on the team calendar (every teammate reminded). We do
NOT read an ATTENDEE list off the event, the event's presence on a
calendar IS the membership, which matches how the assistant books (a copy per
attendee's calendar, or one on the team calendar).

The reminder is rendered from a per-language template table keyed by what
`people.language_for` says the recipient reads, so an English reader gets
English and a Dutch reader keeps Dutch. A single hardcoded string would
send every reader the same language.

Kill switch: `ASSISTANT_MEETING_REMINDERS=1` or the beat does nothing, so the
autonomous send can be turned off instantly (same posture as the other
ASSISTANT_* write switches).

FAILURE POLICY: Tier-2 best-effort. A per-calendar fetch failure is logged
and skipped so one bad calendar never blocks the rest; a Signal send that
fails dead-letters in `shared.signal`. The claim write is Tier-1 (a real
DB failure propagates and 500s the webhook, so the timer retries), that
is the one place a fault stops the run, by design.
"""
from __future__ import annotations

import datetime as _dt
import html
import logging
import os

from apps.assistant.core import people as _people
from apps.assistant.core import state as _state
from apps.assistant.core.tools.agenda import caldav, calendars, talk
from apps.assistant.shared import signal as _signal

log = logging.getLogger("openclaw.meeting_reminders")

_ENABLE_ENV = "ASSISTANT_MEETING_REMINDERS"
# The look-ahead window. It must be at least as wide as the timer cadence
# so no meeting slips between ticks; the claim gate collapses the resulting
# overlap to one send. 13-18 min before start ≈ "a quarter of an hour".
_LEAD_MIN_MINUTES = 13
_LEAD_MAX_MINUTES = 18

# One entry per language the assistant writes in. This beat is deterministic by
# design, so the reminder is a lookup, not a model call: the language comes
# from the people registry and picks a row here. Adding a language is a row.
_DEFAULT_LANGUAGE = "en"
_TEMPLATE = {
    "nl": "Over een kwartier: {summary}.\nVideocall: {link}",
    "en": "In about fifteen minutes: {summary}.\nVideo call: {link}",
}
_FALLBACK_SUMMARY = {
    "nl": "je afspraak",
    "en": "your meeting",
}


def send_due_reminders() -> int:
    """Scan the near window and send one Signal reminder per attendee per
    upcoming video meeting. Returns how many reminders went out this run
    (0 when the switch is off, nobody is reminded, or nothing is due)."""
    if os.environ.get(_ENABLE_ENV, "") != "1":
        return 0
    _state.meeting_reminders.vacuum_old(days=2)
    now = _dt.datetime.now(_dt.timezone.utc)
    window_start = _basic(now + _dt.timedelta(minutes=_LEAD_MIN_MINUTES))
    window_end = _basic(now + _dt.timedelta(minutes=_LEAD_MAX_MINUTES))

    sent = 0
    for name, number in _people.with_send_numbers():
        for event in _upcoming_calls(name, window_start, window_end):
            if _remind_one(name, number, event):
                sent += 1
    if sent:
        log.info("meeting reminders: sent %d", sent)
    return sent


def _calendars_for(name: str) -> list[calendars.Calendar]:
    """The calendars to scan for one teammate: their own scope's calendars
    plus the team calendar, de-duplicated by URL. So a private meeting
    on their own calendar and a team ritual on the team calendar both reach
    them."""
    found, _unknown = calendars.read_calendars(name)
    team = calendars.calendars().get(calendars.TEAM_KEY)
    if team is not None:
        found = found + [team]
    seen: set[str] = set()
    unique: list[calendars.Calendar] = []
    for calendar in found:
        if calendar.url not in seen:
            seen.add(calendar.url)
            unique.append(calendar)
    return unique


def _upcoming_calls(name: str, window_start: str, window_end: str) -> list[dict]:
    """Every busy event with a Talk call link starting in the window, across
    this teammate's calendars. A per-calendar fetch failure is skipped, not
    fatal (Tier-2)."""
    events: list[dict] = []
    for calendar in _calendars_for(name):
        try:
            status, body = calendar.request(
                "REPORT",
                "",
                caldav.time_range_query(window_start, window_end, expand=caldav.is_icloud(calendar.url)),
                {"Content-Type": "application/xml; charset=utf-8", "Depth": "1"},
            )
        except Exception as exc:  # noqa: BLE001, Tier-2: one bad calendar must not stop the rest
            log.warning("reminder scan failed for %s on %s: %s", name, calendar.display, exc)
            continue
        if status >= 300:
            log.warning("reminder scan HTTP %s for %s on %s", status, name, calendar.display)
            continue
        for event in caldav.parse_events(_unescape_xml(body)):
            if caldav.is_busy(event) and talk.is_call_link(event.get("LOCATION", "")):
                events.append(event)
    return events


def _remind_one(name: str, number: str, event: dict) -> bool:
    """Send one reminder for `event` to `name` at `number`, once. Returns True
    iff a reminder was actually sent this call (the claim was fresh AND the
    Signal send succeeded).

    The claim is keyed on the CALL and its start, not the event's UID: one
    call booked on two calendars is two resources with two UIDs (the owner's Work
    copy and a team calendar copy), and keyed by UID it would remind the owner
    twice. The start is normalised to UTC so the same moment written with a
    TZID on one calendar and as UTC on another is still one meeting."""
    link = talk.extract_call_link(event.get("LOCATION", ""))
    if not event.get("UID", "") or not link:
        return False
    start = caldav.parse_dt(event.get("DTSTART", "")).strftime("%Y%m%dT%H%M%SZ")
    key = f"{number}|{link}|{start}"
    if not _state.meeting_reminders.claim(key):
        return False  # already reminded this person about this occurrence
    body = _message(event, link, _language_for(name))
    if not _signal.send("", body, recipient=number):
        log.warning("meeting reminder to %s dead-lettered", number)
        return False
    # Outbound is memory: record it in this person's chat thread so the assistant
    # knows it reminded them. Best-effort, a storage hiccup must not turn a
    # delivered reminder into a failure.
    try:
        _state.append_chat_turn(number, "assistant", body, loop="meeting-reminder")
    except Exception as exc:  # noqa: BLE001, Tier-2: the send already landed
        log.warning("could not record reminder in %s thread: %s", number, exc)
    return True


def _language_for(name: str) -> str:
    """Which language this teammate's reminder is written in.

    The registry decides (`people.language_for`), never the event: a Dutch
    meeting title is not a statement about the reader.
    A teammate the registry says nothing about gets English, matching the
    English default block `people.render` hands an unknown reader.
    """
    return _people.language_for(name) or _DEFAULT_LANGUAGE


def _message(event: dict, link: str, language: str) -> str:
    """The plain-text reminder line in `language`. Signal has no markdown, so
    plain text only."""
    template = _TEMPLATE.get(language, _TEMPLATE[_DEFAULT_LANGUAGE])
    summary = _display(event.get("SUMMARY", ""), language)
    return template.format(summary=summary, link=link)


def _display(value: str, language: str) -> str:
    """Undo the RFC 5545 TEXT escaping so a summary reads naturally in the
    message (a stored 'Lunch\\, review' shows as 'Lunch, review'). An empty
    summary falls back to a plain phrase in the reader's language. HTML
    entities are decoded too, for the titles stored before `caldav.ical_text`
    started decoding them."""
    unescaped = html.unescape(
        value.replace("\\n", " ").replace("\\N", " ")
        .replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")
    ).strip()
    return unescaped or _FALLBACK_SUMMARY.get(language, _FALLBACK_SUMMARY[_DEFAULT_LANGUAGE])


def _basic(moment: _dt.datetime) -> str:
    """A UTC datetime as iCalendar basic UTC ('20260716T140000Z')."""
    return moment.astimezone(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _unescape_xml(body: str) -> str:
    return body.replace("&#13;", "").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
