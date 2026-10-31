"""Read-only `agenda_view` tool, upcoming events on a chosen calendar.

Runs a CalDAV time-range REPORT against one of the calendars the assistant can
reach (the team calendar, or a teammate's calendar shared into the
`assistant` account, see `calendars.py`). `who` picks the scope: a key like
`team`/`alex`/`sam`, or `all` to fan out across every known calendar.
Times in the result are ALREADY local, with the zone on the line:
`caldav.format_event` converts once, in code, so no caller converts again. Each listed line also carries the event id in `[assistant-abc]` form.
Recurring events are expanded to the concrete instance(s) in the window: iCloud
does it server-side, Nextcloud (which drops events under server expand) is
expanded client-side (`caldav.expand_recurring`), so a repeating team calendar
event shows its real next date, not the series-start date. Every answer then
goes through the client-side expansion and a window check, because iCloud
sometimes sends a master anyway and its window is loose.

Tool-module grammar: NAME, DEFINITION, execute.

FAILURE POLICY: non-2xx responses and a missing token come back as
text for the LLM to react to; raises propagate to the registry's
defended Tier-2 catch.
"""
from __future__ import annotations

import datetime
from typing import Any

from apps.assistant.core.tools.agenda import caldav, calendars
from apps.assistant.core.tools.meta.text import truncate

NAME = "agenda_view"

_MAX_DAYS = 31
# How far around the window a bounded series is looked for: one that ended in
# the last four weeks explains a gap where a standing meeting used to be, and
# one ending in the next two weeks is still time to extend.
_SERIES_LOOK_BACK = datetime.timedelta(days=28)
_SERIES_LOOK_AHEAD = datetime.timedelta(days=14)


DEFINITION: dict[str, Any] = {
    "name": NAME,
    "description": (
        "Events on the calendars you can reach, with UIDs; who='all' to find one "
        "to change. Times are already local time; quote them as they are. "
        "Every listed event occurs in the window, even a recurring one showing "
        "an earlier series start."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "who": {
                "type": "string",
                "description": (
                    "Teammate key, 'team' or 'all'. Default: the person you are "
                    "talking to plus the team calendar."
                ),
                "default": calendars.TEAM_KEY,
            },
            "days_ahead": {
                "type": "integer",
                "description": "Max 31.",
                "default": 7,
            },
            "days_back": {
                "type": "integer",
                "description": "Max 31.",
                "default": 0,
            },
        },
        "required": [],
    },
}


def execute(tool_input: dict[str, Any]) -> str:
    days_ahead = min(int(tool_input.get("days_ahead", 7)), _MAX_DAYS)
    days_back = min(int(tool_input.get("days_back", 0)), _MAX_DAYS)
    now = datetime.datetime.now(datetime.timezone.utc)
    start = (now - datetime.timedelta(days=days_back)).strftime("%Y%m%dT%H%M%SZ")
    end = (now + datetime.timedelta(days=days_ahead)).strftime("%Y%m%dT%H%M%SZ")

    # No `who` means the speaker's own calendar plus the team calendar; the schema
    # default documents the fallback for a loop where nobody is speaking.
    who = tool_input.get("who")
    if who is None or (isinstance(who, str) and not who.strip()):
        who = calendars.default_scope_keys()
    targets, unknown = calendars.read_calendars(who)
    if unknown:
        return f"unknown calendar {', '.join(unknown)}; known: {', '.join(calendars.known_scopes())} or 'all'."
    if not targets:
        return f"no calendar configured for {who!r}."

    if len(targets) == 1:
        return _one_calendar(targets[0], start, end)
    return _many_calendars(targets, start, end)


def _expand(events: list[dict], start: str, end: str) -> list[dict]:
    """Concrete instances in the window. Nextcloud returns the recurring
    master, so it is expanded client-side, dropping the day an override in the
    same resource already replaced (the whole resource goes in at once, which
    is what makes that visible). iCloud expands server-side but sometimes sends
    an unexpanded master anyway, and its window is loose, so its answer takes
    the same expansion and every answer is checked against the window;
    an instance iCloud already expanded carries no RRULE and passes through."""
    return caldav.in_window(caldav.expand_all(events, start, end), start, end)


def _one_calendar(calendar: calendars.Calendar, start: str, end: str) -> str:
    status, body = _query(calendar, start, end)
    if status >= 300:
        return f"agenda_view failed: HTTP {status}: {truncate(body)}"
    events = sorted(_expand(caldav.parse_events(_unescape_xml(body)), start, end), key=caldav.sort_key)
    ending = _ending_series(calendar, start, end)
    if not events:
        return truncate("\n".join([f"No {calendar.display} events between {start} and {end}.", *ending]))
    lines = [f"{calendar.display} {start}..{end} ({len(events)} event(s)):"]
    lines += [caldav.format_event(event, with_id=True) for event in events]
    return truncate("\n".join(lines + ending))


def _many_calendars(targets: list[calendars.Calendar], start: str, end: str) -> str:
    blocks = [f"Agenda {start}..{end}:"]
    for calendar in targets:
        status, body = _query(calendar, start, end)
        if status >= 300:
            blocks.append(f"{calendar.display}: query failed HTTP {status}")
            continue
        events = sorted(_expand(caldav.parse_events(_unescape_xml(body)), start, end), key=caldav.sort_key)
        ending = [f"  {line}" for line in _ending_series(calendar, start, end)]
        if not events:
            blocks.append("\n".join([f"{calendar.display}: no events", *ending]))
            continue
        lines = [f"{calendar.display} ({len(events)} event(s)):"]
        lines += [f"  {caldav.format_event(event, with_id=True)}" for event in events]
        blocks.append("\n".join(lines + ending))
    return truncate("\n".join(blocks))


def _ending_series(calendar: calendars.Calendar, start: str, end: str) -> list[str]:
    """Lines naming each repeating series on `calendar` whose last occurrence
    falls between four weeks before the window and two weeks after it, or
    nothing. Without them a series that ran out reads as a free slot and one
    about to run out lapses unannounced.

    A separate read without server expand, because an expanded answer strips
    the RRULE and a series that ended before the window is not in the window's
    answer at all. A failed read adds nothing: the events above it are still
    right, and this block only ever adds a warning.
    """
    look_from = _shifted(start, -_SERIES_LOOK_BACK)
    look_to = _shifted(end, _SERIES_LOOK_AHEAD)
    status, body = _query(calendar, look_from, look_to, expand=False)
    if status >= 300:
        return []
    masters = caldav.parse_events(_unescape_xml(body))
    lines: list[str] = []
    for event in masters:
        last = caldav.series_last_start(event)
        if last is None or not look_from <= last.strftime("%Y%m%dT%H%M%SZ") < look_to:
            continue
        if _continued(event, last, masters):
            continue
        uid = event.get("UID", "").split("  [", 1)[0].strip()
        lines.append(
            f"Series ending: {event.get('SUMMARY', '(no title)')}, last occurrence "
            f"{caldav.human_local(last.strftime('%Y%m%dT%H%M%SZ'))[:10]}, no dates after that [{uid}]"
        )
    return lines


def _continued(ended: dict[str, Any], last: datetime.datetime, masters: list[dict[str, Any]]) -> bool:
    """Whether another series with the same title carries on after `ended`:
    one that repeats with no end, or one whose last occurrence is later. When a
    weekly series ends and is replaced by a new one with the same title, naming the old one as ended would read as a lapsed meeting.
    """
    title = ended.get("SUMMARY")
    for other in masters:
        if other is ended or other.get("SUMMARY") != title or "RRULE" not in other:
            continue
        other_last = caldav.series_last_start(other)
        if other_last is None or other_last > last:
            return True
    return False


def _shifted(utc_basic: str, delta: datetime.timedelta) -> str:
    """A UTC-basic time moved by `delta`, still UTC basic."""
    moment = datetime.datetime.strptime(utc_basic, "%Y%m%dT%H%M%SZ") + delta
    return moment.strftime("%Y%m%dT%H%M%SZ")


def _query(calendar: calendars.Calendar, start: str, end: str, expand: bool | None = None) -> tuple[int, str]:
    return calendar.request(
        "REPORT",
        "",
        caldav.time_range_query(start, end, expand=caldav.is_icloud(calendar.url) if expand is None else expand),
        {"Content-Type": "application/xml; charset=utf-8", "Depth": "1"},
    )


def _unescape_xml(body: str) -> str:
    # calendar-data arrives XML-escaped inside the multistatus response.
    return body.replace("&#13;", "").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
