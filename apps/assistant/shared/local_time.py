"""Write the UTC clock times in a message to a person on the local clock.

Data and receipts are UTC and end in Z, and that is right: a log, a tool
receipt and the deploy record are read by machines and by a person checking
one against another. A message on a phone is read by the owner, who reads
local time. Principle 2 (`core/principles.py`) asks the model to write
every time as local and say so, and prose alone cannot hold it: a released
page that joins several held drafts could otherwise carry the same moment in
both clocks, one draft written in UTC and another in local time.

`in_local_time(text, now)` is the deterministic half. It finds a clock time
the text itself marks as UTC ("14:12 UTC", "14:12:05 UTC", "14:12Z", an ISO
stamp ending in Z or +00:00, with or without its date) and writes it the way
principle 2 words it, "16:12 local (CEST)", with the offset of the
day that time falls on. A time that names no zone is left alone: nothing here
may guess which clock a bare "14:12" was read off, with one exception: the
first end of a range whose zone is written after its second end
("14:00-15:00 UTC", "between 14:00 and 15:00 UTC") is on that same clock, so
both ends move together. A link or a backtick code span inside the message
is machine text and passes through byte for byte.

A time without a date takes the day nearest `now` that puts it within twelve
hours, which only matters on the two days a year the offset changes. A
rewrite that would print the same time twice ("16:12 CEST
(14:12 UTC)", once converted) keeps one. With no timezone database on the box
the text goes out as written: a UTC time correctly labelled costs the reader
a sum, never the fact.

`shared.signal.send` is the one caller, because every page, pen message and
teammate message leaves through it. A send with a subject is a machine page
and is passed on untouched.
"""
from __future__ import annotations

from apps.assistant.shared.zone import LOCAL_ZONE_NAME

import logging
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

log = logging.getLogger("openclaw.local_time")

_LOCAL_ZONE = LOCAL_ZONE_NAME

# A clock time the text marks as UTC. The lookbehind keeps it from starting
# inside a longer number or a version string; "UTC" followed by an offset
# ("UTC+2") is a zone the writer already converted, so it is not matched.
_CLOCK = (
    r"(?P<{name}hour>[01]\d|2[0-3]):(?P<{name}minute>[0-5]\d)"
    r"(?::(?P<{name}second>[0-5]\d))?"
)
_UTC_MARK = r"(?:\.\d+)?(?:\s?UTC\b(?![+-]\d)|Z\b|\+00:00\b)"
_UTC_TIME_RE = re.compile(
    r"(?<![\w:.+-])"
    r"(?:(?P<date>\d{4}-\d{2}-\d{2})[T ])?"
    + _CLOCK.format(name="")
    + _UTC_MARK
)
# A range whose zone is written once, after its second end: "14:00-15:00 UTC",
# "14:00 to 15:00 UTC", "between 14:00 and 15:00 UTC". Both ends are on the
# clock the marker names, so both are rewritten; converting only the marked
# end would turn a one-hour window into a three-hour one.
_UTC_RANGE_RE = re.compile(
    r"(?<![\w:.+-])"
    + _CLOCK.format(name="start_")
    + r"(?P<connector>\s*[\u2013\u2014-]\s*|\s+(?:to|until|and)\s+)"
    + _CLOCK.format(name="")
    + _UTC_MARK
)
# Machine text pasted inside a person's message: a link or a code span. Its
# characters are a value someone may copy, so they pass through byte for byte.
_MACHINE_SPAN_RE = re.compile(r"(`[^`]*`|https?://\S+)")
# The same moment possibly written twice once both halves are local: what the
# model wrote itself ("16:12 local (CEST)", "16:12 CEST"), then its
# own UTC conversion in brackets. `_without_echo` compares the two by value.
_ECHO_RE = re.compile(
    r"(?P<first>"
    r"(?P<hour>\d{2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?"
    r" (?:local (?:time )?)?(?:\((?P<zone>[A-Z]{2,5}|[+-]\d{2,4})\)|(?P<bare_zone>[A-Z]{2,5})\b)"
    r")"
    r" \((?P<echo_hour>\d{2}):(?P<echo_minute>\d{2})(?::(?P<echo_second>\d{2}))?"
    r" local time \((?P<echo_zone>[A-Z]{2,5}|[+-]\d{2,4})\)\)"
)


def in_local_time(text: str, now: datetime | None = None) -> str:
    """`text` with every UTC-marked clock time written in local."""
    try:
        zone = ZoneInfo(_LOCAL_ZONE)
    except Exception as exc:  # noqa: BLE001, Tier-2: no tzdata is not a lost message
        log.warning("local_time could not read the zone (%s); UTC left as written", exc)
        return text
    moment_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    # The split keeps its delimiters at the odd indexes: those are the
    # machine spans, and only the prose between them is rewritten.
    pieces = _MACHINE_SPAN_RE.split(text)
    return "".join(
        piece if index % 2 else _prose_in_local_time(piece, moment_now, zone)
        for index, piece in enumerate(pieces)
    )


def _prose_in_local_time(text: str, moment_now: datetime, zone: ZoneInfo) -> str:
    """One stretch of prose with its UTC times and ranges on the local clock."""
    ranges_done = _UTC_RANGE_RE.sub(
        lambda match: _local_range(match, moment_now, zone), text
    )
    rewritten = _UTC_TIME_RE.sub(
        lambda match: _local_words(match, moment_now, zone), ranges_done
    )
    return _ECHO_RE.sub(_without_echo, rewritten)


def _without_echo(match: re.Match) -> str:
    """The local time the model wrote, its bracketed conversion dropped when
    that names the same moment ("16:12" and "16:12:00" are one clock)."""
    first = (
        match.group("hour"),
        match.group("minute"),
        match.group("second") or "00",
        match.group("zone") or match.group("bare_zone"),
    )
    echo = (
        match.group("echo_hour"),
        match.group("echo_minute"),
        match.group("echo_second") or "00",
        match.group("echo_zone"),
    )
    return match.group("first") if first == echo else match.group(0)


def _local_words(match: re.Match, now: datetime, zone: ZoneInfo) -> str:
    """One matched UTC time as principle 2 writes it, the date only when the
    text named one and it is not today on the reader's clock."""
    moment = _utc_moment(match, now)
    if moment is None:
        return match.group(0)
    local = moment.astimezone(zone)
    words = f"{_clock(local, match.group('second'))} local time ({local.tzname()})"
    if match.group("date") and local.date() != now.astimezone(zone).date():
        return f"{local.day} {local:%b} {words}"
    return words


def _local_range(match: re.Match, now: datetime, zone: ZoneInfo) -> str:
    """One matched UTC range with both ends on the local clock, the zone
    said once when both ends share it and at each end when the offset changes
    inside the window."""
    end = _utc_moment(match, now).astimezone(zone)
    start = _range_start(match, end.astimezone(timezone.utc)).astimezone(zone)
    start_clock = _clock(start, match.group("start_second"))
    end_clock = _clock(end, match.group("second"))
    connector = match.group("connector")
    if start.tzname() == end.tzname():
        return f"{start_clock}{connector}{end_clock} local time ({end.tzname()})"
    return (
        f"{start_clock} local time ({start.tzname()}){connector}"
        f"{end_clock} local time ({end.tzname()})"
    )


def _range_start(match: re.Match, end: datetime) -> datetime:
    """The UTC moment a range opens: its clock on the end's day, or the day
    before when that would put it after the end."""
    start = end.replace(
        hour=int(match.group("start_hour")),
        minute=int(match.group("start_minute")),
        second=int(match.group("start_second") or 0),
    )
    return start - timedelta(days=1) if start > end else start


def _clock(local: datetime, second: str | None) -> str:
    """`local` as HH:MM, or HH:MM:SS when the text wrote seconds."""
    return f"{local:%H:%M:%S}" if second else f"{local:%H:%M}"


def _utc_moment(match: re.Match, now: datetime) -> datetime | None:
    """The UTC moment a match names, its day from the text or nearest `now`;
    None for a date that is not a real one."""
    written_day = match.groupdict().get("date")
    if written_day:
        try:
            day = date.fromisoformat(written_day)
        except ValueError:
            return None
        return _on(day, match)
    candidates = [_on(now.date() + timedelta(days=shift), match) for shift in (-1, 0, 1)]
    return min(candidates, key=lambda candidate: abs(candidate - now))


def _on(day: date, match: re.Match) -> datetime:
    """The match's clock time on `day`, in UTC."""
    return datetime(
        day.year,
        day.month,
        day.day,
        int(match.group("hour")),
        int(match.group("minute")),
        int(match.group("second") or 0),
        tzinfo=timezone.utc,
    )
