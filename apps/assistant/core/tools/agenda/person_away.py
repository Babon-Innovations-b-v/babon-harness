"""Who is away, and until when, read off the calendars the assistant already has.

Without this, the assistant could hand a teammate a job while that teammate
is away. Not because the data is missing: `agenda_availability` can return
"BUSY, Holiday" from a week-long event with no transport, auth or parse error
anywhere. Away-ness needs a representation. As free text in the journal,
which nothing deterministic can read, every gate would treat "I know nothing about them" and "they are at their desk" as the same
answer.

This module gives it one. `status(name) -> Away` is a plain callable, so a
send seam can consult it without an LLM in the loop; `execute` is the same
answer for the model, through the usual tool grammar (NAME, DEFINITION,
execute).

Three outcomes, never two:

    away      a block covering right now runs longer than a single day
    present   the calendars were read and no day-long block covers now
    unknown   there is no calendar to read, reading it failed, or the only
              block covering now is a single all-day entry

The third one is the point. A teammate can resolve to no calendar scope at
all, and a CalDAV fetch can fail; if either collapsed into "present", silence
would read as availability and we would be back to handing work to someone on
a beach.

How away-ness is decided:

  * STATUS:CANCELLED is skipped, TRANSP is IGNORED (`caldav.is_scheduled`).
    A slot check must skip a free-marked all-day banner; a holiday is often
    written as exactly that banner, and one that is OPAQUE today need not be
    next time, so `is_busy` is deliberately not reused here, and not
    changed either, because availability depends on it.
  * the SPAN classifies: DTEND - DTSTART of a full day or more, covering now
    (`caldav.covers_full_day`). No summary keyword matching: no keyword list
    would ever contain every private title a person writes.
  * a span of a full day or more but LESS than two says nothing either way.
    A Dutch calendar carries single all-day banners all the time (a birthday,
    a kantoordag, a deadline, a sprint marker), and TRANSP is ignored here so
    a free-marked one counts too; reading those as away would refuse every
    handover to that person for the day. One day off is written the same way, so the
    honest answer is `unknown`, not a guess in either direction.
  * only the DATES come back, never the summary. A private event title must
    not reach a prompt block other teammates can see.

Cost is bounded: only the scopes that actually resolve are scanned, and a
result is cached briefly so one pass over the team is one fetch per person.

FAILURE POLICY: Tier-2 per the assistant overlay (`apps/assistant/CLAUDE.md`). Every CalDAV fault, timeout
and bad status renders as `unknown` with a plain reason; nothing here raises,
so an away check can never block a beat.
"""
from __future__ import annotations

import datetime as _dt
import logging
import time
from dataclasses import dataclass
from typing import Any

from apps.assistant.core.tools.agenda import caldav, calendars
from apps.assistant.core.tools.meta.text import truncate

log = logging.getLogger("openclaw.agenda.person_away")

NAME = "person_away"

AWAY = "away"
PRESENT = "present"
UNKNOWN = "unknown"

# The probe window: a CalDAV time-range REPORT matches every event OVERLAPPING
# the range, so a few minutes around now is enough to catch a week-long block
# without dragging in next week's events.
_PROBE_MINUTES = 5
# One pass over the team asks about each person once; this collapses the
# repeat lookups a single pass makes (the gate, then the block) into one fetch.
_CACHE_SECONDS = 300
# Longer than this and a block covering now is an absence, not a marker. A
# single all-day entry is exactly one day (DTEND is exclusive), and it is far
# more often a birthday or a kantoordag than a holiday, so it decides nothing.
_AWAY_MINIMUM = _dt.timedelta(days=2)
_AMBIGUOUS_REASON = (
    "one all-day entry covers today, which reads the same as a day off and as "
    "a marker"
)


DEFINITION: dict[str, Any] = {
    "name": NAME,
    "description": (
        "Whether a teammate is away (holiday, or out more than a day) and until "
        "when: away, present or unknown. Unknown is not available; say so."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "person": {
                "type": "string",
                "description": "Omit for everyone.",
            },
        },
    },
}


@dataclass(frozen=True)
class Away:
    """One teammate's away-ness: the verdict plus the dates behind it.

    `since` and `until` are ISO dates ('2026-08-18') and are empty unless the
    state is away. `reason` explains an unknown in plain words; it never
    carries an event summary.
    """

    name: str
    state: str
    since: str = ""
    until: str = ""
    reason: str = ""


_cache: dict[str, tuple[float, Away]] = {}


def reset_cache() -> None:
    """Drop the per-pass cache, so the next `status` call fetches fresh."""
    _cache.clear()


def status(name: str) -> Away:
    """Whether `name` is away right now, present, or unknown. Never raises."""
    key = name.strip().lower()
    cached = _cache.get(key)
    if cached is not None and (time.monotonic() - cached[0]) < _CACHE_SECONDS:
        return cached[1]
    verdict = _look_up(name)
    _cache[key] = (time.monotonic(), verdict)
    return verdict


def _look_up(name: str) -> Away:
    """The uncached verdict for one teammate."""
    scope = calendars.scopes().get(name.strip().lower())
    if scope is None or not scope.read:
        return Away(name=name, state=UNKNOWN, reason="no calendar I can read")
    now = _dt.datetime.now(_dt.timezone.utc)
    window_start = now.strftime("%Y%m%dT%H%M%SZ")
    window_end = (now + _dt.timedelta(minutes=_PROBE_MINUTES)).strftime("%Y%m%dT%H%M%SZ")

    spans: list[tuple[_dt.datetime, _dt.datetime]] = []
    errors: list[str] = []
    for calendar in scope.read:
        found, error = _spans_covering(calendar, window_start, window_end, now)
        spans.extend(found)
        if error:
            errors.append(error)
    return _classify(name, spans, errors)


def _classify(
    name: str, spans: list[tuple[_dt.datetime, _dt.datetime]], errors: list[str]
) -> Away:
    """The verdict for one teammate from the day-long spans covering now plus
    whatever could not be read.

    Only a span longer than a single day is an absence. A one-day span is a
    banner as often as it is a day off, and calling it away would refuse every
    handover to that person for the day, so it comes back `unknown`: the same
    answer this module gives for a calendar it could not read, and for the same
    reason, that a guess in either direction is worse than saying so.
    """
    absences = [span for span in spans if (span[1] - span[0]) >= _AWAY_MINIMUM]
    if absences:
        # The block running longest decides the return date: two overlapping
        # holidays must not report the earlier end as "back on".
        start, end = max(absences, key=lambda span: span[1])
        return Away(name=name, state=AWAY, since=_iso_date(start), until=_iso_date(end))
    if errors:
        return Away(name=name, state=UNKNOWN, reason="; ".join(errors))
    if spans:
        return Away(name=name, state=UNKNOWN, reason=_AMBIGUOUS_REASON)
    return Away(name=name, state=PRESENT)


def _spans_covering(
    calendar: calendars.Calendar, window_start: str, window_end: str, now: _dt.datetime
) -> tuple[list[tuple[_dt.datetime, _dt.datetime]], str]:
    """The full-day-or-longer spans on one calendar that cover `now`, plus a
    plain error string when the calendar could not be read ('' when it could).
    A fault here is data, not an exception: the caller renders it as unknown."""
    try:
        http_status, body = calendar.request(
            "REPORT",
            "",
            caldav.time_range_query(window_start, window_end, expand=caldav.is_icloud(calendar.url)),
            {"Content-Type": "application/xml; charset=utf-8", "Depth": "1"},
        )
    except Exception as exc:  # noqa: BLE001, Tier-2: a fault is 'unknown', never a raise
        log.warning("away check failed on %s: %s", calendar.display, exc)
        return [], f"{calendar.display}: {type(exc).__name__}"
    if http_status >= 300:
        return [], f"{calendar.display}: HTTP {http_status}"

    spans: list[tuple[_dt.datetime, _dt.datetime]] = []
    for event in caldav.parse_events(_unescape_xml(body)):
        if not caldav.is_scheduled(event) or not caldav.covers_full_day(event):
            continue
        start, end = caldav.event_span(event)
        if start is not None and end is not None and start <= now < end:
            spans.append((start, end))
    return spans, ""


def _iso_date(moment: _dt.datetime) -> str:
    """A UTC instant as an ISO date. Dates only ever leave this module."""
    return moment.date().isoformat()


def human_date(iso_date: str) -> str:
    """An ISO date as a person reads it ('2026-08-13' -> '13 August'). The
    input unchanged when it is not a date, so a caller never prints a
    traceback into a message."""
    try:
        parsed = _dt.date.fromisoformat(iso_date)
    except ValueError:
        return iso_date
    return f"{parsed.day} {parsed.strftime('%B')}"


def line_for(verdict: Away) -> str:
    """One rendered line for one teammate, dates only, never a summary."""
    if verdict.state == AWAY:
        return f"- {verdict.name}: away until {human_date(verdict.until)}"
    if verdict.state == PRESENT:
        return f"- {verdict.name}: present"
    reason = verdict.reason or "no calendar I can read"
    return f"- {verdict.name}: unknown ({reason}), this is NOT the same as available"


def render_block() -> str:
    """The WHO IS AWAY spine block: every teammate, with the away ones dated
    and the unknown ones named as unknown.

    Empty string when the registry knows nobody, so a caller can paste it
    unconditionally. Handed to the report path rather than wired in here
   : the loops own their own spine.
    """
    from apps.assistant.core import people  # lazy: avoid a core-init cycle

    lines = [line_for(status(name)) for name in people.names()]
    if not lines:
        return ""
    return (
        "WHO IS AWAY, from their calendars, right now. 'unknown' means you "
        "have no calendar for them, it could not be read, or all it says today "
        "is one all-day entry that could mean anything; do not treat it as "
        "available, and do not hand them work without saying you are unsure:\n"
        + "\n".join(lines)
    )


def execute(tool_input: dict[str, Any]) -> str:
    from apps.assistant.core import people  # lazy: avoid a core-init cycle

    person = str(tool_input.get("person", "")).strip()
    wanted = [person] if person else people.names()
    if not wanted:
        return "I have nobody in my people registry, so I cannot say who is away."
    return truncate("\n".join(line_for(status(name)) for name in wanted))


def _unescape_xml(body: str) -> str:
    return body.replace("&#13;", "").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
