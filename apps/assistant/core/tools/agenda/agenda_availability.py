"""Read-only `agenda_availability` tool, is a slot free?.

Given a time window and a set of people, this runs a CalDAV time-range
REPORT against each of their calendars (see `calendars.py`) and reports
who is FREE and who is BUSY, with the clashing events. It is the check
behind conflict-aware planning: "a teammate, plan Friday 14:00" -> the assistant looks
at the owner's and a teammate's calendars for that window, and if the owner is busy it
says so and offers another slot. The proposing is the loop's job; this
tool only reports busy blocks, it does not pick times.

`who` is one key, a list of keys, or 'all' (every known calendar).
`start`/`end` are the candidate window in iCalendar UTC basic format.
Recurrence: the server's time-range filter matches recurring instances
that fall in the window, so a weekly event still shows as busy; the raw
event is surfaced, not the expanded instance.

Tool-module grammar: NAME, DEFINITION, execute.

FAILURE POLICY: a per-calendar non-2xx is reported inline as text for
that person (the other people are still answered); a missing token or
bad time range comes back as text; raises propagate to the registry's
defended Tier-2 catch.
"""
from __future__ import annotations

from typing import Any

from apps.assistant.core.tools.agenda import caldav, calendars
from apps.assistant.core.tools.meta.text import truncate

NAME = "agenda_availability"

_MAX_BUSY_EVENTS = 5


DEFINITION: dict[str, Any] = {
    "name": NAME,
    "description": (
        "FREE or BUSY per person in a time window, with the clashes. Check "
        "attendees before proposing a meeting."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "who": {
                "description": "Teammate key, list of keys, or 'all'.",
                "default": "all",
            },
            "start": {"type": "string", "description": "local time, e.g. '2026-07-17 14:00'."},
            "end": {"type": "string", "description": "local time."},
        },
        "required": ["start", "end"],
    },
}


def execute(tool_input: dict[str, Any]) -> str:
    # Accept local-local times too (like agenda_act), so the model never has
    # to hand-convert to UTC to check a slot; to_utc_basic returns None if unparseable.
    start = caldav.to_utc_basic(str(tool_input.get("start", "")))
    end = caldav.to_utc_basic(str(tool_input.get("end", "")))
    if not start or not end:
        return ("availability needs start and end as local time "
                "('2026-07-17 14:00') or UTC basic (20260717T120000Z).")
    if end <= start:
        return "availability needs end after start."

    people, unknown = calendars.resolve_people(tool_input.get("who", "all"))
    if unknown:
        return f"unknown calendar {', '.join(unknown)}; known: {', '.join(calendars.known_scopes())} or 'all'."

    lines = [f"Availability {start}..{end}:"]
    for scope in people:
        lines.append(_verdict(scope, start, end))
    return truncate("\n".join(lines))


def busy_in_window(scope: calendars.Scope, start: str, end: str) -> tuple[list[dict], list[str]]:
    """The clashing events for one person in [start, end], unioning every
    calendar they read (so a private-calendar clash blocks a work slot), plus
    any per-calendar check errors as text. Shared by the FREE/BUSY verdict here
    and the booking guard in `agenda_act`, so a conflict is scanned the
    same way whether the loop is checking or booking. Empty events + empty
    errors means genuinely free; a non-empty error list means the check could
    not fully run, which the caller must not read as 'free'."""
    events: list[dict] = []
    errors: list[str] = []
    for calendar in scope.read:
        status, body = calendar.request(
            "REPORT",
            "",
            caldav.time_range_query(start, end, expand=caldav.is_icloud(calendar.url)),
            {"Content-Type": "application/xml; charset=utf-8", "Depth": "1"},
        )
        if status >= 300:
            errors.append(f"{calendar.display}: HTTP {status}")
            continue
        # Expand recurring events to their concrete window instances first, on
        # every backend because iCloud sometimes sends an unexpanded master,
        # and drop what does not overlap the window, because iCloud's filter is
        # loose. Then keep only events that actually block the slot: a
        # free-marked (TRANSP:TRANSPARENT) or cancelled event is not a clash.
        parsed = caldav.parse_events(_unescape_xml(body))
        parsed = caldav.in_window(caldav.expand_all(parsed, start, end), start, end)
        events.extend(event for event in parsed if caldav.is_busy(event))
    events.sort(key=caldav.sort_key)
    return events, errors


def _verdict(scope: calendars.Scope, start: str, end: str) -> str:
    """FREE/BUSY for one person, unioning every calendar they read (so a
    private-calendar clash blocks a work slot)."""
    events, errors = busy_in_window(scope, start, end)
    if errors and not events:
        return f"- {scope.display}: check failed ({'; '.join(errors)})"
    if not events:
        return f"- {scope.display}: free"
    shown = "; ".join(caldav.format_event(event) for event in events[:_MAX_BUSY_EVENTS])
    more = f" (+{len(events) - _MAX_BUSY_EVENTS} more)" if len(events) > _MAX_BUSY_EVENTS else ""
    return f"- {scope.display}: BUSY, {shown}{more}"


def _unescape_xml(body: str) -> str:
    return body.replace("&#13;", "").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
