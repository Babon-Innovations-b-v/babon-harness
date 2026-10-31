"""`agenda_act` tool, the assistant writes to a calendar.

Same safety shape as `github_act`, scaled to the smaller blast radius
(a calendar event is trivially reversible):

  1. KILL SWITCH. Writes refuse unless ``ASSISTANT_AGENDA_WRITE=1`` in the
     pod env. Unset and the assistant's agenda goes read-only instantly.
  2. OWN IDENTITY. Every write authenticates as the `assistant` account
     (the calendar's own login), so agenda changes are attributable.
  3. AUDIT. Each action lands in ``state.assistant_actions`` once it has
     actually succeeded (kinds ``agenda_add`` / ``agenda_move`` /
     ``agenda_update`` / ``agenda_remove``); a failed CalDAV write is NOT
     logged as done.

Changing anything else about an event is `update`: a read-modify-write that
splices the named properties into the existing resource and leaves every other
line alone, so a retitled meeting keeps its alarm, its attendees and its call
link. A field that arrives EMPTY is left alone rather than cleared, because the
model fills schema fields freely and the other reading would let it blank
somebody's meeting. Removing a location or description is
its own explicit list, `clear`, so a correction such as "no call link" can
reach the event that every later reader and reminder takes it from.

Rescheduling is its own action, `move`, NOT a remove plus an add: a move
rewrites the event's times under its existing UID, so the calendar shows one
event that shifted. Doing it as remove+add asks the model to name the old
event from memory, and when it names the wrong id (or one that no longer
exists) the add still lands and the person is left with two meetings.

An id that no calendar holds is a MISS, never a near-miss: a lookup only
resolves an href whose calendar-data actually carries that UID. Falling back
to the first event in the response would mean that, on a server that ignores
a UID filter, a made-up id could silently hit an unrelated event.

The `calendar` param picks the scope to write (`team` = shared team calendar,
or a teammate scope like `alex`), resolved through `calendars`. An add has NO
default calendar, and the team calendar takes an add only when the caller says
it is a whole-team event (`team_event`): everything there reminds every
teammate, so a two-person call booked there reminds everyone who is not in
it; it belongs on each attendee's own calendar. Removal is
actor-gated: a PERSON (chat) may remove any event on a managed calendar;
on patrol (actor ``assistant``) the assistant removes only events it created itself
(``assistant-`` UID), never autonomously wiping a human's appointment. A
recurring event offers three removals: ``occurrence`` (a date) cancels one
day via an EXDATE while the series continues; ``whole_series`` deletes the
whole thing; neither is refused with both options named. `move` takes the same
two words: ``occurrence`` moves one day out of the series, ``whole_series``
shifts every occurrence by rewriting the master, and that one refuses when the
rule's BYDAY says the requested weekday is not a day the series falls on.

Tool-module grammar: NAME, DEFINITION, execute.

FAILURE POLICY: refusal states and non-2xx responses return as text; the
audit write is Tier-1 (its failure propagates to the registry's defended
catch rather than skipping the log).
"""
from __future__ import annotations

import datetime as _dt
from typing import Any
from urllib.parse import urlparse

from apps.assistant.core.tools import write_guard
from apps.assistant.core.tools.agenda import agenda_availability, caldav, calendars
from apps.assistant.core.tools.meta.text import truncate

NAME = "agenda_act"

_ENABLE_ENV = "ASSISTANT_AGENDA_WRITE"
_AUTONOMOUS_ACTOR = "assistant"  # the patrol/self actor; a person's name means user-directed
_MAX_CONFLICTS = 5           # clashing events named back before the list is cut
_SERIES_HORIZON_DAYS = 183   # how far ahead a repeating add's occurrences are checked for clashes
_CLEARABLE = {"location": "LOCATION", "description": "DESCRIPTION"}  # what update's `clear` may remove


DEFINITION: dict[str, Any] = {
    "name": NAME,
    "description": (
        "Write a calendar as assistant: add, move, update or remove an event. update "
        "changes only the fields you pass (`clear` removes one). Reschedule with "
        "move, never remove then add. Remove any event only when a person asks; "
        "on your own, only events you created. An add names `calendar`: a "
        "meeting goes on each attendee's own calendar, one add each; 'team' (the "
        "team calendar) is for whole-team events only and needs team_event=true. "
        "Times are local time. A busy window is refused unless "
        "ignore_conflict=true, which only the person can ask for."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["add", "move", "update", "remove"]},
            "calendar": {"type": "string", "description": "Teammate key ('alex') or 'team'. Required on add."},
            "team_event": {"type": "boolean", "description": "add on 'team': the whole team attends."},
            "summary": {"type": "string", "description": "Title."},
            "start": {"type": "string", "description": "local time, e.g. '2026-07-11 14:00'. update: with end."},
            "end": {"type": "string", "description": "local time. update: with start."},
            "location": {"type": "string", "description": "Optional."},
            "description": {"type": "string", "description": "Optional body text."},
            "clear": {"type": "array", "items": {"type": "string", "enum": ["location", "description"]}, "description": "update: fields to remove."},
            "rrule": {"type": "string", "description": "iCal RRULE without 'RRULE:', e.g. 'FREQ=WEEKLY;BYDAY=MO'."},
            "ignore_conflict": {"type": "boolean", "description": "Book over a clash; only when the person said so."},
            "uid": {"type": "string", "description": "From agenda_view, never from memory."},
            "whole_series": {"type": "boolean", "description": (
                "remove/move: every occurrence. A recurring event needs this or "
                "`occurrence`."
            )},
            "occurrence": {"type": "string", "description": "remove/move: 'YYYY-MM-DD' of one occurrence."},
        },
        "required": ["action"],
    },
}


def execute(tool_input: dict[str, Any], actor: str = "assistant") -> str:
    disabled = write_guard.require_enabled(_ENABLE_ENV, "change the agenda")
    if disabled:
        return disabled
    action = str(tool_input.get("action", ""))
    scope_key = str(tool_input.get("calendar") or "").strip()
    if not scope_key and action == "add":
        return ("add needs `calendar`: the calendar of each person the event is for, "
                f"one add per person; known: {', '.join(calendars.known_scopes())}.")
    scope = calendars.scopes().get((scope_key or calendars.TEAM_KEY).lower())
    if scope is None:
        return f"unknown calendar {scope_key!r}; known: {', '.join(calendars.known_scopes())}."
    if scope.write is None:
        return f"'{scope.display}' has no calendar I can write to; I can read it but not add or remove events there."
    if action == "add":
        return _add(tool_input, actor, scope)
    if action == "move":
        return _move(tool_input, actor, scope)
    if action == "update":
        return _update(tool_input, actor, scope)
    if action == "remove":
        return _remove(tool_input, actor, scope.write)
    return f"unknown action {action!r}; use add, move, update or remove."


def _add(tool_input: dict[str, Any], actor: str, scope: calendars.Scope) -> str:
    calendar = scope.write
    summary = str(tool_input.get("summary", "")).strip()
    start = caldav.to_utc_basic(str(tool_input.get("start", "")))
    end = caldav.to_utc_basic(str(tool_input.get("end", "")))
    if not summary or not start or not end:
        return ("add needs summary, start and end. Times can be local time "
                "(e.g. '2026-07-11 14:00') or UTC basic (e.g. 20260711T120000Z).")
    if _writes_to_team_calendar(scope) and not tool_input.get("team_event"):
        return _team_refusal()
    refusal, unverified = _slot_check(tool_input, scope, start, end, verb="add")
    if refusal:
        return refusal
    rrule = str(tool_input.get("rrule", "")).strip().removeprefix("RRULE:")
    series_refusal, series_note = _series_check(tool_input, scope, start, end, rrule) if rrule else ("", "")
    if series_refusal:
        return series_refusal
    uid = caldav.new_uid()
    status, body = calendar.request(
        "PUT",
        f"{uid}.ics",
        caldav.build_event(
            uid,
            summary,
            start,
            end,
            str(tool_input.get("location", "")).strip(),
            str(tool_input.get("description", "")).strip(),
            rrule,
        ),
        {"Content-Type": "text/calendar; charset=utf-8"},
    )
    if status >= 300:
        return f"add failed: HTTP {status}: {truncate(body)}"
    # Audit only a write that actually landed (matches github_act ordering).
    write_guard.audit("agenda_add", f"{calendar.key} {uid}", f"{summary} @ {start}", actor=actor)
    # Citeable receipt: the human local time + the id, so the model quotes this
    # back verbatim instead of restating a guessed time/day.
    suffix = f", repeats {rrule}{series_note}" if rrule else ""
    return f"added to {calendar.display}: {summary}, {caldav.human_range(start, end)}{suffix}{unverified} [{uid}]"


def _series_check(
    tool_input: dict[str, Any], scope: calendars.Scope, start: str, end: str, rrule: str,
) -> tuple[str, str]:
    """Free/busy for the LATER occurrences of a repeating add: `(refusal, note)`.

    `_slot_check` reads the first occurrence only, so on its own it would call
    both people free for a weekly series on the strength of one Monday. This expands the rule up to
    `_SERIES_HORIZON_DAYS` ahead, reads each calendar ONCE across that span,
    and refuses naming the dates that clash. The note always says how far the
    check reached, so the receipt never claims more than was read."""
    if tool_input.get("ignore_conflict"):
        return "", ""
    series = {"DTSTART": start, "DTEND": end, "RRULE": rrule}
    horizon = _days_after(start, _SERIES_HORIZON_DAYS)
    later = [occ for occ in caldav.expand_recurring(series, start, horizon) if occ["DTSTART"] != start]
    if not later or any("RRULE" in occ for occ in later):
        return "", "; only the first occurrence was checked for clashes, not the later ones"
    busy, errors = agenda_availability.busy_in_window(scope, later[0]["DTSTART"], later[-1]["DTEND"])
    clashes = [
        f"{caldav.human_local(occ['DTSTART'])} ({caldav.format_event(event)})"
        for occ in later for event in busy if _overlaps(occ, event)
    ]
    if clashes:
        return (f"not booked: {scope.display} is already busy on later occurrences of this series: "
                f"{'; '.join(clashes[:_MAX_CONFLICTS])}. Pick another slot, or add it again with "
                "ignore_conflict set if they want it booked over the clash."), ""
    if errors:
        return "", ("; could not confirm the later occurrences were free: " + "; ".join(errors))
    reach = f"; all {len(later) + 1} occurrences up to {caldav.human_local(later[-1]['DTSTART'])} were free"
    if caldav.expand_recurring(series, horizon, _days_after(horizon, _SERIES_HORIZON_DAYS)):
        reach += ", later ones not checked"
    return "", reach


def _overlaps(occurrence: dict[str, Any], event: dict[str, Any]) -> bool:
    """Whether a busy `event` overlaps one expanded `occurrence` of a series."""
    occ_start, occ_end = caldav.event_span(occurrence)
    event_start, event_end = caldav.event_span(event)
    if None in (occ_start, occ_end, event_start, event_end):
        return False
    return event_start < occ_end and occ_start < event_end


def _days_after(utc_basic: str, days: int) -> str:
    """The UTC-basic moment `days` after `utc_basic`."""
    moment = _dt.datetime.strptime(utc_basic, "%Y%m%dT%H%M%SZ") + _dt.timedelta(days=days)
    return moment.strftime("%Y%m%dT%H%M%SZ")


def _writes_to_team_calendar(scope: calendars.Scope) -> bool:
    """Whether an add on `scope` lands on the team calendar, judged by the
    calendar it writes to rather than by its name.

    An `AGENDA_SCOPES` person whose write key is `team` (a teammate with no
    calendar of their own) is the team calendar under another name, and checking
    the scope's name let a two-person call through that door."""
    team = calendars.calendars().get(calendars.TEAM_KEY)
    return team is not None and scope.write is not None and scope.write.url == team.url


def _team_refusal() -> str:
    """Why an add on the team calendar that is not a whole-team event did not
    land, and where it goes instead.

    Everything on the team calendar reminds every teammate (`meeting_reminders`
    scans it for all of them), so a call between two people booked there
    reaches the ones who are not in it. The person scopes are named back so
    the model has the keys for the per-attendee adds."""
    own = [key for key, scope in calendars.scopes().items() if not _writes_to_team_calendar(scope)]
    return ("not booked: the team calendar is only for events the whole team attends, and "
            "everything on it reminds everyone. A meeting between specific people goes on "
            "each attendee's own calendar: add it once per person, with calendar set to "
            f"theirs ({', '.join(own) or 'no personal calendars are connected'}). If the whole "
            "team really attends, add it again with team_event set to true.")


def _slot_check(
    tool_input: dict[str, Any], scope: calendars.Scope, start: str, end: str,
    verb: str, skip_uid: str = "",
) -> tuple[str, str]:
    """Free/busy BEFORE the write: `(refusal, unverified)`, both empty
    when the slot is free.

    Checking before the write, not after, keeps a clash from landing. Scan the target scope
    over the slot and refuse a real clash unless the caller explicitly
    overrides. A check that could not run (errors, no conflicts found) does not
    block, but `unverified` goes on the receipt so the assistant never claims a check it
    did not complete. `skip_uid` drops the event being moved from its own
    result, so shifting a meeting by half an hour does not clash with itself.
    """
    if tool_input.get("ignore_conflict"):
        return "", ""
    conflicts, errors = agenda_availability.busy_in_window(scope, start, end)
    if skip_uid:
        conflicts = [event for event in conflicts if event.get("UID", "") != skip_uid]
    if conflicts:
        shown = "; ".join(caldav.format_event(event) for event in conflicts[:_MAX_CONFLICTS])
        return (f"not booked: {scope.display} is already busy then, {shown}. "
                f"Pick another slot, or {verb} it again with ignore_conflict set "
                f"if they want it booked over the clash."), ""
    if errors:
        return "", " (could not confirm the slot was free: " + "; ".join(errors) + ")"
    return "", ""


def _move(tool_input: dict[str, Any], actor: str, scope: calendars.Scope) -> str:
    """Reschedule an event to a new time, keeping its identity.

    A one-off is rewritten in place under the same UID, so every client shows
    the SAME meeting at the new time; one occurrence of a series is dropped
    with an EXDATE and re-booked as a one-off carrying the original's title and
    call link. Neither path can leave the person with two meetings, which
    remove-then-add did whenever the removal named the wrong event.
    """
    uid = str(tool_input.get("uid", "")).strip()
    if not uid or "/" in uid:
        return "move needs a valid event id; take it from agenda_view, not from memory."
    start = caldav.to_utc_basic(str(tool_input.get("start", "")))
    end = caldav.to_utc_basic(str(tool_input.get("end", "")))
    if not start or not end:
        return ("move needs the new start and end. Times can be local time "
                "(e.g. '2026-08-31 14:00') or UTC basic (e.g. 20260831T120000Z).")
    located = _locate_event(uid, scope.write)
    if located is None:
        return f"no event with id {uid} on any calendar I manage; list the day with agenda_view and use the id it shows."
    target, href, etag = located
    status, raw = target.request_href("GET", href)
    if status >= 300:
        return f"move failed: could not read {uid}: HTTP {status}: {truncate(raw)}"
    was = _describe(raw, uid)
    occurrence = str(tool_input.get("occurrence", "")).strip()
    if "RRULE:" in caldav.unfold(raw):
        if occurrence:
            return _move_occurrence(
                tool_input, target, scope, href, etag, raw, uid, was, start, end, occurrence, actor)
        if tool_input.get("whole_series"):
            return _shift_series(target, href, etag, raw, uid, was, start, end, actor)
        return (f"'{was}' ({uid}) is a repeating event. Say which day you mean by passing "
                "occurrence as that date (YYYY-MM-DD); I move that one and leave the rest "
                "of the series where it is. To shift EVERY occurrence to the new time, "
                "move it again with whole_series set.")

    refusal, unverified = _slot_check(tool_input, scope, start, end, verb="move", skip_uid=uid)
    if refusal:
        return refusal
    status, body = target.request_href(
        "PUT", href, caldav.replace_times(raw, start, end),
        {"Content-Type": "text/calendar; charset=utf-8", **caldav.if_match(etag)},
    )
    if status >= 300:
        return _write_failure("move failed", status, body, etag, target, href, uid)
    write_guard.audit("agenda_move", f"{target.key} {uid}", f"moved {was} to {start}", actor=actor)
    return (f"moved {was} on {target.display} to {caldav.human_range(start, end)}"
            f"{unverified} [{uid}]")


def _move_occurrence(
    tool_input: dict[str, Any], target: calendars.Calendar, scope: calendars.Scope,
    href: str, etag: str | None, master_ics: str, uid: str, was: str, start: str,
    end: str, occurrence: str, actor: str,
) -> str:
    """Move ONE occurrence out of a series: EXDATE that day on the master, then
    book the new time as a one-off carrying the original's title, location (the
    call link) and description. The rest of the series is untouched."""
    occ = caldav.occurrence_date(occurrence)
    if occ is None:
        return f"I need the occurrence date as YYYY-MM-DD to move one day of '{was}'."
    dtstart = caldav.master_dtstart_line(master_ics)
    if dtstart is None:
        return f"could not read the start of '{was}' ({uid}) to move one occurrence."
    exdate = caldav.exdate_line(dtstart, occ)
    if exdate is None:
        return f"could not build the exclusion for '{was}' on {occurrence}."
    refusal, unverified = _slot_check(tool_input, scope, start, end, verb="move", skip_uid=uid)
    if refusal:
        return refusal
    status, body = target.request_href(
        "PUT", href, caldav.splice_exdate(master_ics, exdate),
        {"Content-Type": "text/calendar; charset=utf-8", **caldav.if_match(etag)},
    )
    if status >= 300:
        return _write_failure(
            f"move failed: could not drop {occurrence} from the series", status, body, etag,
            target, href, uid)
    summary = caldav.text_property(master_ics, "SUMMARY") or "event"
    new_uid = caldav.new_uid()
    status, body = target.request_href(
        "PUT", f"{new_uid}.ics",
        caldav.build_event(
            new_uid, summary, start, end,
            caldav.text_property(master_ics, "LOCATION"),
            caldav.text_property(master_ics, "DESCRIPTION"),
        ),
        {"Content-Type": "text/calendar; charset=utf-8"},
    )
    if status >= 300:
        # The day is already excluded, so say so rather than imply nothing changed.
        return (f"half-done: {occurrence} was dropped from '{summary}' but booking the new "
                f"time failed (HTTP {status}: {truncate(body)}); add it by hand or retry.")
    write_guard.audit("agenda_move", f"{target.key} {uid}", f"moved {occ} of {summary} to {start}", actor=actor)
    return (f"moved the {occurrence} '{summary}' on {target.display} to "
            f"{caldav.human_range(start, end)}; the rest of the series is unchanged"
            f"{unverified} [{new_uid}]")


def _shift_series(
    target: calendars.Calendar, href: str, etag: str | None, master_ics: str,
    uid: str, was: str, start: str, end: str, actor: str,
) -> str:
    """Move EVERY occurrence of a series, by rewriting the master's times.

    The sharpest write in this module: one PUT changes every future occurrence
    on everybody's phone, which is why it is asked for explicitly
    (`whole_series`) and never inferred from a move that named no day.

    It refuses rather than half-honours when the request and the rule disagree.
    A weekly rule takes its weekday from BYDAY, so a new start on another
    weekday would leave the series on its old day at a new time, which is not
    the move anybody meant. And it never claims a slot check it cannot run:
    `_slot_check` reads one window, while a series occupies windows without
    end, so the receipt says the later occurrences were not checked."""
    master = caldav.master_event(caldav.parse_events(master_ics))
    rrule = str(master.get("RRULE", "")).split("  [", 1)[0] if master else ""
    weekdays = caldav.rrule_weekdays(rrule)
    if weekdays and caldav.weekday_token(start) not in weekdays:
        return (f"not moved: '{was}' ({uid}) repeats on the weekday its own rule names "
                f"(BYDAY={','.join(weekdays)}), and {caldav.human_local(start)} is not one of "
                "those days. The rule would win and the series would stay where it is, so I "
                "have changed nothing. Give a new time on one of those days, or say you want "
                "the repeat pattern itself changed and I will update the rule.")
    status, body = target.request_href(
        "PUT", href, caldav.shift_series(master_ics, start, end),
        {"Content-Type": "text/calendar; charset=utf-8", **caldav.if_match(etag)},
    )
    if status >= 300:
        return _write_failure("move failed: could not shift the series", status, body, etag, target, href, uid)
    write_guard.audit("agenda_move", f"{target.key} {uid}", f"shifted the whole series {was} to {start}", actor=actor)
    return (f"moved the whole series {was} on {target.display} to "
            f"{caldav.human_range(start, end)}; every occurrence follows, and I did not check "
            f"the later ones for clashes [{uid}]")


def _update_values(tool_input: dict[str, Any]) -> tuple[dict[str, str], str]:
    """The iCalendar properties an update should splice, or a refusal saying
    why it cannot be honoured.

    Only fields that are PRESENT and NON-EMPTY are collected: an empty value
    means leave it alone, never clear it. A model fills the fields of a schema
    freely, and the other reading would let one empty string blank somebody's
    meeting. Start and end travel together, so the length of
    a meeting is never inferred from half an instruction."""
    values: dict[str, str] = {}
    for field, prop in (("summary", "SUMMARY"), ("location", "LOCATION"), ("description", "DESCRIPTION")):
        written = str(tool_input.get(field, "")).strip()
        if written:
            values[prop] = written
    rrule = str(tool_input.get("rrule", "")).strip().removeprefix("RRULE:")
    if rrule:
        values["RRULE"] = rrule
    start = str(tool_input.get("start", "")).strip()
    end = str(tool_input.get("end", "")).strip()
    if bool(start) != bool(end):
        return {}, "update needs BOTH start and end to change the time, so the length is never a guess."
    if start:
        start_utc, end_utc = caldav.to_utc_basic(start), caldav.to_utc_basic(end)
        if not start_utc or not end_utc:
            return {}, ("update could not read those times. Give local time "
                        "(e.g. '2026-08-31 14:00') or UTC basic (e.g. 20260831T120000Z).")
        values["DTSTART"], values["DTEND"] = start_utc, end_utc
    return values, ""


def _cleared_properties(tool_input: dict[str, Any]) -> tuple[list[str], str]:
    """The iCalendar properties an update should REMOVE, from the explicit
    `clear` list, or a refusal saying why it cannot be honoured.

    An empty field still never clears anything; only naming the field here
    does. That is the one way a correction like "the link is not needed" can reach
    the event: without it the call link stays in the LOCATION and the next
    reminders carry it to everyone."""
    named = tool_input.get("clear") or []
    if isinstance(named, str):
        named = [named]
    cleared: list[str] = []
    for field in named:
        prop = _CLEARABLE.get(str(field).strip().lower())
        if prop is None:
            return [], f"update can only clear {' or '.join(_CLEARABLE)}, not {field!r}."
        if str(tool_input.get(str(field).strip().lower(), "")).strip():
            return [], f"update was asked both to set and to clear {field}; say which."
        if prop not in cleared:
            cleared.append(prop)
    return cleared, ""


def _update(tool_input: dict[str, Any], actor: str, scope: calendars.Scope) -> str:
    """Change the fields of an existing event in place, leaving everything the
    caller did not name exactly as it was.

    Read-modify-write over a lossless splice under an `If-Match`, so the blast
    radius is one resource and a concurrent edit refuses the write rather than
    overwriting it. A recurring event's TIME is out of scope here: rewriting a
    master's DTSTART moves every future occurrence, which is `move` with
    whole_series, so update refuses it and names that route."""
    uid = str(tool_input.get("uid", "")).strip()
    if not uid or "/" in uid:
        return "update needs a valid event id; take it from agenda_view, not from memory."
    values, refusal = _update_values(tool_input)
    if refusal:
        return refusal
    cleared, refusal = _cleared_properties(tool_input)
    if refusal:
        return refusal
    if not values and not cleared:
        return ("update needs at least one field to change: summary, start with end, location, "
                "description or rrule, or a field named in clear. A field you leave out keeps "
                "the value it has.")
    located = _locate_event(uid, scope.write)
    if located is None:
        return f"no event with id {uid} on any calendar I manage; list the day with agenda_view and use the id it shows."
    target, href, etag = located
    status, raw = target.request_href("GET", href)
    if status >= 300:
        return f"update failed: could not read {uid}: HTTP {status}: {truncate(raw)}"
    was = _describe(raw, uid)
    retimed = "DTSTART" in values
    if retimed and "RRULE:" in caldav.unfold(raw):
        return (f"'{was}' ({uid}) is a repeating event, so a new time would move every future "
                "occurrence. Use move with whole_series to shift the series, or move with "
                "occurrence to move one day; update still changes its other fields.")
    unverified = ""
    if retimed:
        clash, unverified = _slot_check(
            tool_input, scope, values["DTSTART"], values["DTEND"], verb="update", skip_uid=uid)
        if clash:
            return clash
    status, body = target.request_href(
        "PUT", href, caldav.splice_properties(raw, values, drop=cleared),
        {"Content-Type": "text/calendar; charset=utf-8", **caldav.if_match(etag)},
    )
    if status >= 300:
        return _write_failure("update failed", status, body, etag, target, href, uid)
    fields = ", ".join([name.lower() for name in values] + [f"cleared {name.lower()}" for name in cleared])
    when = f"; now {caldav.human_range(values['DTSTART'], values['DTEND'])}" if retimed else ""
    write_guard.audit("agenda_update", f"{target.key} {uid}", f"updated {fields} of {was}", actor=actor)
    return f"updated {was} on {target.display}: changed {fields}{when}{unverified} [{uid}]"


def _remove(tool_input: dict[str, Any], actor: str, calendar: calendars.Calendar) -> str:
    uid = str(tool_input.get("uid", "")).strip()
    if not uid or "/" in uid:
        return "remove needs a valid event id."
    # A person can ask the assistant to delete ANY event (audited). On its OWN
    # (patrol, actor 'assistant') it still deletes only what it created, it must
    # never autonomously wipe a human's appointment.
    if actor.strip().lower() == _AUTONOMOUS_ACTOR and not uid.startswith("assistant-"):
        return "on my own I only remove events I created; ask me directly and I'll remove any event you point me at."
    located = _locate_event(uid, calendar)
    if located is None:
        return f"no event with id {uid} on any calendar I manage."
    target, href, etag = located
    status, raw = target.request_href("GET", href)
    recurring = status < 300 and "RRULE:" in caldav.unfold(raw)
    summary = _describe(raw, uid) if status < 300 else uid
    occurrence = str(tool_input.get("occurrence", "")).strip()

    if recurring and occurrence and not tool_input.get("whole_series"):
        return _cancel_occurrence(target, href, etag, raw, uid, summary, occurrence, actor)
    # Recurring safety: deleting the resource cancels the WHOLE series, so
    # refuse a recurring master unless the caller explicitly means the series.
    if recurring and not tool_input.get("whole_series"):
        return (f"'{summary}' ({uid}) is a repeating event. To cancel just one occurrence, "
                "remove it again with occurrence set to that date (YYYY-MM-DD). To delete the "
                "whole series, remove it again with whole_series set.")
    status, body = target.request_href("DELETE", href)
    if status >= 300:
        return f"remove failed: HTTP {status}: {truncate(body)}"
    write_guard.audit("agenda_remove", f"{target.key} {uid}", f"removed {summary}", actor=actor)
    return f"removed {summary} from {target.display} [{uid}]"


def _cancel_occurrence(
    target: calendars.Calendar, href: str, etag: str | None, master_ics: str,
    uid: str, summary: str, occurrence: str, actor: str,
) -> str:
    """Cancel ONE occurrence of a recurring event by adding a matching EXDATE
    to the master and writing it back (read-modify-write), so the series
    continues without that day."""
    occ = caldav.occurrence_date(occurrence)
    if occ is None:
        return f"I need the occurrence date as YYYY-MM-DD to cancel one day of '{summary}'."
    dtstart = caldav.master_dtstart_line(master_ics)
    if dtstart is None:
        return f"could not read the start of '{summary}' ({uid}) to cancel one occurrence."
    exdate = caldav.exdate_line(dtstart, occ)
    if exdate is None:
        return f"could not build the exclusion for '{summary}' on {occurrence}."
    updated = caldav.splice_exdate(master_ics, exdate)
    status, body = target.request_href(
        "PUT", href, updated,
        {"Content-Type": "text/calendar; charset=utf-8", **caldav.if_match(etag)},
    )
    if status >= 300:
        return _write_failure("cancel occurrence failed", status, body, etag, target, href, uid)
    write_guard.audit("agenda_remove", f"{target.key} {uid}", f"cancelled {occ} of {summary}", actor=actor)
    return f"cancelled the {occurrence} occurrence of {summary} on {target.display}; the series continues [{uid}]"


def _write_failure(
    what: str, status: int, body: str, etag: str | None,
    target: calendars.Calendar, href: str, uid: str,
) -> str:
    """The line a person reads when a write did not land. `what` names the
    attempt ('move failed', 'update failed'), `etag` the condition that went
    out with the PUT, and `target`/`href`/`uid` the resource it went to.

    A 412 is its own answer, and it says TWO different things depending on that
    condition. Quoting the server's own etag, a refusal means the event CHANGED
    between our read and our write. With `If-Match: *` it is not an answer at
    all until the resource is read again: a server can refuse that condition
    for an event that still exists, so reading it as "removed" would be wrong. It is a
    different 412 again from the one iCloud answers a UID-filter REPORT with,
    which never reaches here: that one is absorbed by the lookup ladder."""
    if status == 412 and etag:
        return (f"{what}: the event changed on the calendar while I was editing it, so I left it "
                "alone rather than overwrite that change. Look it up again with agenda_view and "
                "try again.")
    if status == 412:
        return _unconditional_refusal(what, target, href, uid)
    return f"{what}: HTTP {status}: {truncate(body)}"


def _unconditional_refusal(what: str, target: calendars.Calendar, href: str, uid: str) -> str:
    """What a 412 to an `If-Match: *` write means, decided by reading the
    resource again rather than assumed: still there, gone, or unknown."""
    status, raw = target.request_href("GET", href)
    if status < 300 and caldav.holds_uid(raw, uid):
        return (f"{what}: {target.display} refused the write (HTTP 412) and the event is still "
                f"there, unchanged: {_describe(raw, uid)}. Nothing changed; tell the person "
                "that, not that it is gone.")
    if status == 404:
        return (f"{what}: the event is not on {target.display} any more (HTTP 404 when I read it "
                "again), so there was nothing to change. Look the day up again with agenda_view.")
    return (f"{what}: {target.display} refused the write (HTTP 412), and reading the event again "
            f"answered HTTP {status}, so I cannot tell whether it is still there. Nothing was "
            "changed by me; check it with agenda_view.")


def _describe(ics_text: str, uid: str) -> str:
    """The event as a person reads it: title AND its actual date and time.

    A receipt naming the title alone hides a wrong hit: a stale id resolved
    to a call two weeks in the past reads the same as the intended one. With
    the date on it, a wrong hit is obvious to
    whoever reads the line. It describes the MASTER of the resource, so
    a series one day of which somebody has moved is named by the series, not by
    that one overriding occurrence."""
    master = caldav.master_event(caldav.parse_events(ics_text))
    return caldav.format_event(master) if master else uid


def _locate_event(uid: str, preferred: calendars.Calendar) -> tuple[calendars.Calendar, str, str | None] | None:
    """Find the calendar + resource href + etag holding this UID, `preferred`
    first then every other managed calendar, so a person can say 'remove X'
    without naming the exact calendar. Three ways, because iCloud rejects (412)
    the UID-filter REPORT that Nextcloud accepts:
      1. direct resource GET of `<uid>.ics` (the assistant's own events, and servers
         that name the file by UID);
      2. a UID-filter REPORT (Nextcloud);
      3. a bounded time-range REPORT, matching the UID in the returned data
         (the iCloud-safe path).
    Every path CHECKS the UID in the calendar-data it got back. Accepting the
    first href in the response when that match fails is only safe on a server
    that honours the filter: Google ignores it and answers with the whole
    collection, so a made-up id would resolve to whichever event happens to
    come first.
    None when no calendar has it.

    The etag is the version the caller quotes back in `If-Match` so a write
    cannot land on top of somebody's own edit. Path 1's GET cannot see it, so
    a hit there asks `_own_event_etag` for it; only when that read fails is it
    None, and the caller then sends `*`, which proves existence and no more."""
    headers = {"Content-Type": "application/xml; charset=utf-8", "Depth": "1"}
    ordered = [preferred] + [cal for cal in calendars.calendars().values() if cal.url != preferred.url]
    for cal in ordered:
        status, raw = cal.request("GET", f"{uid}.ics")
        if status < 300 and caldav.holds_uid(raw, uid):
            return cal, f"{uid}.ics", _own_event_etag(cal, uid)
        status, body = cal.request("REPORT", "", caldav.uid_query(uid), headers)
        if status < 300:
            href = caldav.href_for_uid(body, uid)
            if href:
                return cal, href, caldav.etag_for_uid(body, uid)
        start, end = caldav.wide_window()
        status, body = cal.request("REPORT", "", caldav.time_range_query(start, end), headers)
        if status < 300:
            href = caldav.href_for_uid(body, uid)
            if href:
                return cal, href, caldav.etag_for_uid(body, uid)
    return None


def _own_event_etag(cal: calendars.Calendar, uid: str) -> str | None:
    """The etag of the assistant's own `<uid>.ics` on `cal`, read with a one-resource
    calendar-multiget, or None when the server would not answer one.

    Without it a write goes out as `If-Match: *`, and iCloud can refuse a move
    of an event that is plainly on the calendar with 412."""
    href = urlparse(cal.url).path + f"{uid}.ics"
    status, body = cal.request(
        "REPORT", "", caldav.multiget_query(href), {"Content-Type": "application/xml; charset=utf-8"})
    return caldav.etag_for_uid(body, uid) if status < 300 else None
