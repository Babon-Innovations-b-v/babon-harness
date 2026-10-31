"""Shared CalDAV transport + minimal iCalendar helpers for the agenda
tool group (server = Nextcloud CalDAV).
stdlib only, the openclaw image installs no calendar libraries.

Not a tool module itself (no NAME/DEFINITION), same role as
kubectl/k8s.py: the one place the agenda tools reach the server.
"""
from __future__ import annotations

from apps.assistant.shared.zone import LOCAL_ZONE

import base64
import datetime as _dt
import html
import os
import re
import secrets
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
from zoneinfo import ZoneInfo

_LOCAL_TZ = LOCAL_ZONE
_UTC_BASIC_RE = re.compile(r"^\d{8}T\d{6}Z$")
# local wall-clock formats a person or the model naturally writes.
_LOCAL_FORMATS = (
    "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
    "%Y%m%dT%H%M%S",
)

# AGENDA_BASE_URL is the CalDAV root, normally Nextcloud's
# https://cloud.<domain>/remote.php/dav. BASE_URL is its origin (scheme and
# host), DAV_PATH its path, so a server-absolute href from a multistatus answer
# and a collection name both resolve against the same server.
_DAV_ROOT = os.environ.get("AGENDA_BASE_URL", "").strip().rstrip("/")
_ROOT_PARTS = urllib.parse.urlsplit(_DAV_ROOT)
BASE_URL = f"{_ROOT_PARTS.scheme}://{_ROOT_PARTS.netloc}" if _ROOT_PARTS.netloc else "http://nextcloud"
DAV_PATH = _ROOT_PARTS.path.rstrip("/") or "/remote.php/dav"
_USER_ENV = "AGENDA_USER"
_TOKEN_ENV = "AGENDA_APP_PASSWORD"


def agenda_user() -> str:
    """The account the assistant signs in to the file cloud as."""
    return os.environ.get(_USER_ENV, "").strip()


_TIMEOUT_SECONDS = 20
_MAX_REDIRECTS = 4
# iCloud throttles (503/429) and has brief 502/504 blips; a single retry per
# these turns "add failed: HTTP 503" into a clean success. Bounded hard: at
# most _MAX_RETRIES extra tries, each backoff capped, so a genuinely-down
# server still returns promptly instead of hanging a chat turn.
_RETRY_STATUSES = frozenset({429, 502, 503, 504})
_MAX_RETRIES = 2
_RETRY_BACKOFF_SECONDS = (1.0, 3.0)
_MAX_RETRY_AFTER_SECONDS = 5.0

# Properties surfaced to the LLM, in display order.
_EVENT_FIELDS = ("SUMMARY", "DTSTART", "DTEND", "LOCATION", "RRULE", "UID")
# Properties whose values are RFC 5545 TEXT and must be escaped on the way in.
_TEXT_PROPERTIES = ("SUMMARY", "LOCATION", "DESCRIPTION")
# Properties parsed for logic only (busy/free), never displayed.
_LOGIC_FIELDS = ("TRANSP", "STATUS")
# The instance an overriding VEVENT replaces. Parsed WITH its params, like a
# display field, because its value type has to be comparable to the master's;
# never shown to the model, so it is not in `_EVENT_FIELDS`.
_OVERRIDE_FIELD = "RECURRENCE-ID"


def _retry_after_seconds(headers: Any, attempt: int) -> float:
    """How long to wait before retry `attempt`: the server's Retry-After if it
    sent a small integer one, else a fixed backoff. Capped both ways so a
    hostile or absent header can never stall a chat turn."""
    raw = None
    try:
        raw = headers.get("Retry-After") if headers is not None else None
    except Exception:  # noqa: BLE001, a weird header object must not break the retry
        raw = None
    if raw and str(raw).strip().isdigit():
        return min(float(str(raw).strip()), _MAX_RETRY_AFTER_SECONDS)
    return _RETRY_BACKOFF_SECONDS[min(attempt, len(_RETRY_BACKOFF_SECONDS) - 1)]


def dav_request(
    method: str,
    url: str,
    auth: tuple[str, str],
    body: bytes = b"",
    headers: dict[str, str] | None = None,
    _hop: int = 0,
    _retry: int = 0,
) -> tuple[int, str]:
    """One authenticated CalDAV call to an ABSOLUTE url with (user, password)
    Basic auth; (status, text). This is the general transport behind every
    calendar (Nextcloud's assistant account, a teammate's iCloud, ...), so a
    calendar carries its own server + credentials.

    Redirects on non-GET verbs (PROPFIND/REPORT/PUT/DELETE) are followed by
    hand: urllib only auto-follows GET/HEAD, and iCloud 301s the generic host
    to a partition host. Auth is re-sent because it is rebuilt each hop.

    A transient throttle/blip (429/502/503/504) or a timeout/reset is retried
    up to `_MAX_RETRIES` times with a capped backoff, so an iCloud 503 becomes
    a clean success instead of surfacing 'add failed: HTTP 503' to the person.
    """
    user, password = auth
    credentials = base64.b64encode(f"{user}:{password}".encode()).decode()
    http_request = urllib.request.Request(
        url,
        data=body or None,
        method=method,
        headers={"Authorization": f"Basic {credentials}", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(http_request, timeout=_TIMEOUT_SECONDS) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        # HTTPError is a URLError subclass, so this clause must come first.
        location = error.headers.get("Location")
        if error.code in (301, 302, 307, 308) and location and _hop < _MAX_REDIRECTS:
            return dav_request(method, location, auth, body, headers, _hop + 1, _retry)
        if error.code in _RETRY_STATUSES and _retry < _MAX_RETRIES:
            time.sleep(_retry_after_seconds(error.headers, _retry))
            return dav_request(method, url, auth, body, headers, _hop, _retry + 1)
        return error.code, error.read().decode("utf-8", "replace")
    except (urllib.error.URLError, socket.timeout, TimeoutError) as error:
        if _retry < _MAX_RETRIES:
            time.sleep(_retry_after_seconds(None, _retry))
            return dav_request(method, url, auth, body, headers, _hop, _retry + 1)
        # A DNS/timeout/reset on one calendar returns as text (599) so a
        # multi-calendar answer degrades gracefully instead of raising.
        return 599, f"network error reaching the calendar: {error}"


def request(method: str, path: str, body: bytes = b"", headers: dict[str, str] | None = None) -> tuple[int, str]:
    """A call on the assistant's own account: BASE_URL + server path, signed
    in as AGENDA_USER with AGENDA_APP_PASSWORD."""
    token = os.environ.get(_TOKEN_ENV, "").strip()
    if not token:
        raise RuntimeError(f"{_TOKEN_ENV} is not set")
    return dav_request(method, BASE_URL + path, (agenda_user(), token), body, headers)


def unfold(ics_text: str) -> str:
    """Undo RFC 5545 line folding (a continuation line starts with a space or
    tab) so a property can be matched even if the server folded it."""
    return ics_text.replace("\r\n ", "").replace("\n ", "").replace("\r\n\t", "").replace("\n\t", "")


def parse_events(ics_text: str) -> list[dict[str, str]]:
    """Minimal VEVENT extraction: unfold lines, keep the fields the LLM
    needs. Values are raw iCalendar (UTC basic format or with TZID
    param); recurrence is surfaced as the raw RRULE, not expanded."""
    unfolded: list[str] = []
    for line in ics_text.splitlines():
        if line[:1] in (" ", "\t") and unfolded:
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    events: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in unfolded:
        if line.strip() == "BEGIN:VEVENT":
            current = {}
            continue
        if line.strip() == "END:VEVENT":
            if current:
                events.append(current)
            current = None
            continue
        if current is None or ":" not in line:
            continue
        prop, value = line.split(":", 1)
        name = prop.split(";", 1)[0].upper()
        if (name in _EVENT_FIELDS or name == _OVERRIDE_FIELD) and name not in current:
            current[name] = value.strip() + ("" if ";" not in prop else f"  [{prop.split(';', 1)[1]}]")
        elif name in _LOGIC_FIELDS and name not in current:
            current[name] = value.strip().upper()
        elif name == "EXDATE":
            # EXDATE can repeat and hold comma-separated dates; accumulate ALL
            # (unlike the single-value fields) so client-side expansion can skip
            # cancelled occurrences. Kept as raw value+param strings.
            current.setdefault("EXDATE", []).append(
                value.strip() + ("" if ";" not in prop else f"  [{prop.split(';', 1)[1]}]")
            )
    return events


def _event_moment(value: str) -> _dt.datetime | None:
    """One DTSTART/DTEND value as a local datetime, or None.

    `parse_events` keeps the raw property value and appends the parameters it
    saw, so a value arrives in one of three shapes: `20260817T080000Z` (UTC),
    `20260817T130000  [TZID=Europe/local]` (floating plus its zone), or
    `20260817  [VALUE=DATE]` (all day).
    """
    raw = value.split("  [", 1)[0].strip()
    params = value.split("  [", 1)[1] if "  [" in value else ""
    try:
        if raw.endswith("Z"):
            moment = _dt.datetime.strptime(raw, "%Y%m%dT%H%M%SZ")
            return moment.replace(tzinfo=_dt.timezone.utc).astimezone(_LOCAL_TZ)
        if "T" in raw:
            moment = _dt.datetime.strptime(raw, "%Y%m%dT%H%M%S")
            match = re.search(r"TZID=([^;\]]+)", params)
            zone = _LOCAL_TZ
            if match:
                try:
                    zone = ZoneInfo(match.group(1).strip())
                except Exception:  # noqa: BLE001 - an unknown zone falls back, never raises
                    zone = _LOCAL_TZ
            return moment.replace(tzinfo=zone).astimezone(_LOCAL_TZ)
        return _dt.datetime.strptime(raw, "%Y%m%d").replace(tzinfo=_LOCAL_TZ)
    except ValueError:
        return None


def format_event(event: dict[str, str], with_id: bool = False) -> str:
    """One event as a line a person can read, in local time.

    `with_id` appends the event's own id in brackets (`[assistant-abc]`), which is
    the ONLY supply of ids the model has: the chat prompt, the capability block
    and `agenda_act`'s schema all tell it to take an id from `agenda_view`, and
    once the raw fields were dropped there was none on the line to take. Off by
    default, so a conflict line and a receipt read exactly as before.

    Not raw iCalendar fields (`SUMMARY=... | DTSTART=20260101T080000Z | ...`),
    with some times in UTC and some carrying a TZID: handed straight to the
    model, those leave it to do the timezone conversion while writing a
    sentence, the kind of arithmetic-inside-prose that produces a confidently
    wrong meeting time. The conversion happens here, once, in code.
    """
    summary = event.get("SUMMARY", "(no title)")
    start = _event_moment(event.get("DTSTART", ""))
    end = _event_moment(event.get("DTEND", ""))
    if start is None:
        when = event.get("DTSTART", "time unknown")
    elif start.hour == 0 and start.minute == 0 and (end is None or end - start >= _dt.timedelta(days=1)):
        when = start.strftime("%a %d %b, all day")
    elif end is None:
        when = start.strftime("%a %d %b %H:%M %Z")
    elif end.date() == start.date():
        when = f"{start.strftime('%a %d %b %H:%M')}-{end.strftime('%H:%M')} {start.strftime('%Z')}"
    else:
        when = f"{start.strftime('%a %d %b %H:%M')} to {end.strftime('%a %d %b %H:%M')} {start.strftime('%Z')}"
    line = f"{when}: {summary}"
    location = event.get("LOCATION", "").strip()
    if location:
        line += f", {location}"
    if event.get("RRULE"):
        line += " (repeats)"
    if with_id:
        uid = event.get("UID", "").split("  [", 1)[0].strip()
        if uid:
            line += f" [{uid}]"
    return line


def ical_text(value: str) -> str:
    """Escape a TEXT property value per RFC 5545 (backslash first, then ; , and
    newlines). ONLY for TEXT props (SUMMARY/LOCATION/DESCRIPTION); never for
    UID/DTSTART/RRULE. Without it 'Lunch, review' emits a malformed VEVENT.

    HTML entities are decoded first: the model sometimes writes 'the owner &amp;
    A teammate' into a tool call, and a calendar is plain text, so the entity would
    be stored and read back to people word for word."""
    return (
        html.unescape(value).replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def build_event(uid: str, summary: str, start_utc: str, end_utc: str, location: str = "", description: str = "", rrule: str = "") -> bytes:
    """A minimal UTC VEVENT (times must already be iCalendar basic UTC,
    e.g. 20260711T080000Z). `rrule` is a raw iCalendar recurrence rule
    WITHOUT the `RRULE:` prefix (e.g. `FREQ=WEEKLY;BYDAY=MO;UNTIL=20260928T070000Z`),
    for repeating events like a weekly briefing; empty = one-off."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//the project//assistant-agenda//NL",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{start_utc}",
        f"DTSTART:{start_utc}",
        f"DTEND:{end_utc}",
        f"SUMMARY:{ical_text(summary)}",
    ]
    if rrule:
        lines.append(f"RRULE:{rrule}")
    if location:
        lines.append(f"LOCATION:{ical_text(location)}")
    if description:
        lines.append(f"DESCRIPTION:{ical_text(description)}")
    lines += ["END:VEVENT", "END:VCALENDAR", ""]
    return "\r\n".join(lines).encode()


def new_uid() -> str:
    return f"assistant-{secrets.token_hex(8)}"


def to_utc_basic(value: str) -> str | None:
    """Normalise a time to iCalendar UTC basic (…Z). An already-UTC-basic
    value passes through; a local wall-clock time ('2026-07-11 14:00' or
    '20260711T140000') is converted to UTC with the correct CET/CEST offset
    (so the model never does DST math by hand). None if unparseable."""
    value = value.strip()
    if _UTC_BASIC_RE.match(value):
        return value
    for fmt in _LOCAL_FORMATS:
        try:
            naive = _dt.datetime.strptime(value, fmt)
        except ValueError:
            continue
        return (
            naive.replace(tzinfo=_LOCAL_TZ)
            .astimezone(_dt.timezone.utc)
            .strftime("%Y%m%dT%H%M%SZ")
        )
    return None


def is_icloud(url: str) -> bool:
    """True for an Apple iCloud CalDAV URL. Used to choose the request shape:
    iCloud handles server-side recurrence <expand> well, Nextcloud drops events
    under it, so we expand only on iCloud."""
    return "icloud.com" in url.lower()


def time_range_query(start_utc: str, end_utc: str, expand: bool = False) -> bytes:
    """CalDAV calendar-query REPORT body for VEVENTs in [start, end).

    With `expand=True` the server returns one concrete VEVENT per recurring
    instance in the window (real DTSTART, RRULE stripped) instead of the master
    with its original start; use it on iCloud so 'next week' shows the right
    date. Nextcloud drops events under expand, so leave it False there."""
    data = (
        f'<C:calendar-data><C:expand start="{start_utc}" end="{end_utc}"/></C:calendar-data>'
        if expand
        else "<C:calendar-data/>"
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">\n'
        f"  <D:prop>{data}</D:prop>\n"
        "  <C:filter><C:comp-filter name=\"VCALENDAR\">\n"
        "    <C:comp-filter name=\"VEVENT\">\n"
        f'      <C:time-range start="{start_utc}" end="{end_utc}"/>\n'
        "    </C:comp-filter>\n"
        "  </C:comp-filter></C:filter>\n"
        "</C:calendar-query>\n"
    ).encode()


_FAR_FUTURE = _dt.datetime.max.replace(tzinfo=_dt.timezone.utc)


def parse_dt(raw: str) -> _dt.datetime:
    """Parse a parsed-event DTSTART/DTEND value into an aware UTC datetime, so
    events sort by real chronology, not by string. Handles the three shapes the
    server returns: UTC basic ('20260711T120000Z'), a wall-clock time with a
    TZID param ('20260711T140000  [TZID=Europe/local]'), and an all-day
    DATE ('20260711  [VALUE=DATE]', taken as local midnight). A naive time
    with no zone is read as local. Unparseable sorts last."""
    value, _, param = raw.partition("  [")
    value = value.strip()
    param = param.rstrip("]")
    tzid = ""
    for piece in param.split(";"):
        key, _, val = piece.partition("=")
        if key.strip().upper() == "TZID":
            tzid = val.strip()
    try:
        if _UTC_BASIC_RE.match(value):
            return _dt.datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=_dt.timezone.utc)
        if len(value) == 8 and value.isdigit():  # all-day DATE
            naive = _dt.datetime.strptime(value, "%Y%m%d")
        else:
            naive = _dt.datetime.strptime(value.replace("Z", ""), "%Y%m%dT%H%M%S")
    except ValueError:
        return _FAR_FUTURE
    zone = _LOCAL_TZ
    if tzid:
        try:
            zone = ZoneInfo(tzid)
        except Exception:  # noqa: BLE001, unknown TZID: fall back to local
            zone = _LOCAL_TZ
    return naive.replace(tzinfo=zone).astimezone(_dt.timezone.utc)


def sort_key(event: dict[str, Any]) -> _dt.datetime:
    """Chronological sort key: the event's real start instant in UTC."""
    return parse_dt(event.get("DTSTART", ""))


def is_busy(event: dict[str, Any]) -> bool:
    """Whether this event actually blocks a slot. A TRANSP:TRANSPARENT event
    (marked 'free', e.g. an all-day banner) or a STATUS:CANCELLED one does not
    make the person busy, so availability must not count it as a clash."""
    return event.get("TRANSP", "") != "TRANSPARENT" and event.get("STATUS", "") != "CANCELLED"


def is_scheduled(event: dict[str, Any]) -> bool:
    """Whether this event is still on the calendar at all: only STATUS:CANCELLED
    takes it off.

    The sibling of `is_busy`, and deliberately laxer in one exact way: TRANSP is
    IGNORED. A slot check must skip a free-marked all-day banner, but a holiday
    is very often written as exactly that banner, so reading TRANSP here would
    make a week away look like an ordinary working week. One holiday may be
    written OPAQUE; the next one need not be. `is_busy` stays untouched:
    availability depends on it.
    """
    return event.get("STATUS", "") != "CANCELLED"


def covers_full_day(event: dict[str, Any]) -> bool:
    """Whether the event spans a full day or more (DTEND - DTSTART >= 24h).

    Span is the whole classifier for away-ness: a private title tells us
    nothing a keyword list could match (a private trip title matches none), and
    a title is not ours to read out anyway, but a block of a day or more is
    unambiguous. An event with no DTEND spans nothing.
    """
    start, end = event_span(event)
    return start is not None and end is not None and (end - start) >= _dt.timedelta(days=1)


def event_span(event: dict[str, Any]) -> tuple[_dt.datetime | None, _dt.datetime | None]:
    """The event's (start, end) as aware UTC datetimes, or (None, None) when
    either is missing or unparseable. Dates only ever leave here as instants;
    the SUMMARY is never touched."""
    raw_start = event.get("DTSTART", "")
    raw_end = event.get("DTEND", "")
    if not raw_start or not raw_end:
        return None, None
    start = parse_dt(raw_start)
    end = parse_dt(raw_end)
    if start == _FAR_FUTURE or end == _FAR_FUTURE:
        return None, None
    return start, end


# ── client-side recurrence expansion (Nextcloud) ──────────────────────────
# iCloud expands recurring events server-side (`<C:expand>`), but Nextcloud
# DROPS events under expand, so its time-range REPORT returns the recurring
# MASTER with its ORIGINAL DTSTART, not the instance in the window, which would
# make a weekly meeting show a weeks-old date. So for Nextcloud
# we expand the RRULE ourselves, stdlib-only, and iCloud's answer goes through
# the same expansion because iCloud sometimes returns an unexpanded master too
#. Bounded hard against a pathological rule; supports the rules our
# meetings and birthdays use (DAILY/WEEKLY/MONTHLY/YEARLY, INTERVAL, WEEKLY
# BYDAY, COUNT, UNTIL, EXDATE).
_WEEKDAY = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
_MAX_RECUR_ITERS = 4000
_MAX_RECUR_INSTANCES = 366


def _dtstart_local(raw: str) -> tuple[_dt.datetime | None, _dt.tzinfo]:
    """(naive wall-clock, zone) for a DTSTART/EXDATE/UNTIL value, so recurrence
    steps in the event's own timezone (wall-clock stays put across DST). A Z
    value is UTC; a TZID value its zone; a bare/all-day value local."""
    value, _, param = raw.partition("  [")
    value = value.strip()
    tzid = ""
    for piece in param.rstrip("]").split(";"):
        key, _, val = piece.partition("=")
        if key.strip().upper() == "TZID":
            tzid = val.strip()
    if _UTC_BASIC_RE.match(value):
        return _dt.datetime.strptime(value, "%Y%m%dT%H%M%SZ"), _dt.timezone.utc
    if len(value) == 8 and value.isdigit():
        return _dt.datetime.strptime(value, "%Y%m%d"), _LOCAL_TZ
    try:
        naive = _dt.datetime.strptime(value.replace("Z", ""), "%Y%m%dT%H%M%S")
    except ValueError:
        return None, _LOCAL_TZ
    zone: _dt.tzinfo = _LOCAL_TZ
    if tzid:
        try:
            zone = ZoneInfo(tzid)
        except Exception:  # noqa: BLE001, unknown TZID falls back to local
            zone = _LOCAL_TZ
    return naive, zone


def _parse_rrule(rrule: str) -> dict[str, str]:
    parts: dict[str, str] = {}
    for token in rrule.split(";"):
        key, _, val = token.partition("=")
        if key.strip():
            parts[key.strip().upper()] = val.strip()
    return parts


def _exdate_days(event: dict[str, Any]) -> set[str]:
    """The YYYYMMDD dates cancelled by EXDATE, matched at day granularity (our
    cancellations are per-day, `agenda_act` writes a date-matched EXDATE)."""
    days: set[str] = set()
    for raw in event.get("EXDATE", []):
        value = raw.partition("  [")[0]
        for piece in value.split(","):
            digits = re.sub(r"\D", "", piece)[:8]
            if len(digits) == 8:
                days.add(digits)
    return days


def _iter_starts(start: _dt.datetime, freq: str, interval: int, byday: list[int]):
    """Yield instance wall-clock starts from `start` forward, chronologically,
    for the supported FREQ. Bounded by the caller."""
    if freq == "DAILY":
        current = start
        for _ in range(_MAX_RECUR_ITERS):
            yield current
            current = current + _dt.timedelta(days=interval)
    elif freq == "WEEKLY" and byday:
        monday = start - _dt.timedelta(days=start.weekday())
        emitted = 0
        block = 0
        while emitted < _MAX_RECUR_ITERS:
            week = monday + _dt.timedelta(weeks=interval * block)
            for weekday in sorted(byday):
                candidate = (week + _dt.timedelta(days=weekday)).replace(
                    hour=start.hour, minute=start.minute, second=start.second
                )
                if candidate < start:
                    continue
                yield candidate
                emitted += 1
                if emitted >= _MAX_RECUR_ITERS:
                    return
            block += 1
    elif freq == "WEEKLY":
        current = start
        for _ in range(_MAX_RECUR_ITERS):
            yield current
            current = current + _dt.timedelta(weeks=interval)
    elif freq == "MONTHLY":
        for step in range(_MAX_RECUR_ITERS):
            months = start.month - 1 + interval * step
            year = start.year + months // 12
            month = months % 12 + 1
            try:
                yield start.replace(year=year, month=month)
            except ValueError:
                continue  # day-of-month absent in a short month: skipped, per RFC
    elif freq == "YEARLY":
        for step in range(_MAX_RECUR_ITERS):
            try:
                yield start.replace(year=start.year + interval * step)
            except ValueError:
                continue  # 29 February in a year without one: skipped, per RFC
    else:
        yield start  # unknown FREQ: leave it as the single master instance


def _rule_steps(rule: dict[str, str]) -> tuple[str, int, list[int]]:
    """(FREQ, INTERVAL, BYDAY weekdays) of a parsed RRULE: how it steps."""
    freq = rule.get("FREQ", "").upper()
    interval = max(int(rule["INTERVAL"]) if rule.get("INTERVAL", "").isdigit() else 1, 1)
    byday = [_WEEKDAY[d] for d in rule.get("BYDAY", "").split(",") if d in _WEEKDAY] if freq == "WEEKLY" else []
    return freq, interval, byday


def _rule_bound(rule: dict[str, str]) -> tuple[int | None, _dt.datetime | None]:
    """(COUNT, UNTIL as aware UTC) of a parsed RRULE: where it stops. Both None
    for a series that repeats for ever."""
    count = int(rule["COUNT"]) if rule.get("COUNT", "").isdigit() else None
    until = None
    if rule.get("UNTIL"):
        until_local, until_zone = _dtstart_local(rule["UNTIL"])
        if until_local is not None:
            until = until_local.replace(tzinfo=until_zone).astimezone(_dt.timezone.utc)
    return count, until


def series_last_start(event: dict[str, Any]) -> _dt.datetime | None:
    """The start of the last occurrence of a bounded series, as aware UTC, or
    None for a one-off, an open-ended series, or a rule that cannot be read.

    A series that ran out looks exactly like a free slot in a time-range read:
    the server returns nothing for the week after its last date. That can
    let the assistant call the owner's Monday open over a standing 10:00 whose
    series had ended the week before. This is what lets a reader say a
    series has ended or is about to, instead of finding out from the gap.
    """
    if "RRULE" not in event or not event.get("DTSTART"):
        return None
    start_local, zone = _dtstart_local(event["DTSTART"])
    if start_local is None:
        return None
    rule = _parse_rrule(event["RRULE"])
    count, until = _rule_bound(rule)
    if count is None and until is None:
        return None
    freq, interval, byday = _rule_steps(rule)
    last = None
    for occurrence, candidate in enumerate(_iter_starts(start_local, freq, interval, byday), start=1):
        if count is not None and occurrence > count:
            break
        candidate_utc = candidate.replace(tzinfo=zone).astimezone(_dt.timezone.utc)
        if until is not None and candidate_utc > until:
            break
        last = candidate_utc
    return last


def expand_recurring(event: dict[str, Any], window_start_utc: str, window_end_utc: str) -> list[dict[str, Any]]:
    """The concrete instances of `event` that overlap
    [window_start_utc, window_end_utc). Overlap and not start, because an
    all-day instance starts at local midnight, before a window that opens
    at 08:00 the same day, and is still that day's event. A non-recurring event returns itself
    (the server already window-filtered it); a recurring master is expanded
    into per-instance copies (own DTSTART/DTEND, RRULE removed). Unparseable →
    the master unchanged, so we never drop an event."""
    if "RRULE" not in event or not event.get("DTSTART"):
        return [event]
    start_local, zone = _dtstart_local(event["DTSTART"])
    if start_local is None:
        return [event]
    start_utc = parse_dt(event["DTSTART"])
    end_utc = parse_dt(event["DTEND"]) if event.get("DTEND") else start_utc
    duration = end_utc - start_utc if end_utc > start_utc else _dt.timedelta(0)
    window_start = _dt.datetime.strptime(window_start_utc, "%Y%m%dT%H%M%SZ").replace(tzinfo=_dt.timezone.utc)
    window_end = _dt.datetime.strptime(window_end_utc, "%Y%m%dT%H%M%SZ").replace(tzinfo=_dt.timezone.utc)

    rule = _parse_rrule(event["RRULE"])
    freq, interval, byday = _rule_steps(rule)
    count, until = _rule_bound(rule)
    excluded = _exdate_days(event)

    instances: list[dict[str, Any]] = []
    occurrence = 0
    for candidate in _iter_starts(start_local, freq, interval, byday):
        occurrence += 1
        if count is not None and occurrence > count:
            break
        candidate_utc = candidate.replace(tzinfo=zone).astimezone(_dt.timezone.utc)
        if until is not None and candidate_utc > until:
            break
        if candidate_utc >= window_end:
            break
        if candidate_utc + duration <= window_start:
            continue
        if candidate.strftime("%Y%m%d") in excluded:
            continue
        instance = dict(event)
        instance.pop("RRULE", None)
        instance.pop("EXDATE", None)
        instance["DTSTART"] = candidate_utc.strftime("%Y%m%dT%H%M%SZ")
        instance["DTEND"] = (candidate_utc + duration).strftime("%Y%m%dT%H%M%SZ")
        instances.append(instance)
        if len(instances) >= _MAX_RECUR_INSTANCES:
            break
    return instances


def _day_digits(raw: str) -> str:
    """The YYYYMMDD date of a raw iCalendar datetime value, or ''. Day
    granularity, the same as `_exdate_days` uses: an override names the
    instance it replaces at whatever value type the master carries, so the date
    is the part that compares cleanly across UTC, TZID and all-day values."""
    digits = re.sub(r"\D", "", raw.partition("  [")[0])[:8]
    return digits if len(digits) == 8 else ""


def expand_all(events: list[dict[str, Any]], window_start_utc: str, window_end_utc: str) -> list[dict[str, Any]]:
    """The concrete instances in the window for a WHOLE set of parsed events.

    `expand_recurring` sees one event at a time, so it cannot know that another
    VEVENT in the same resource already replaced one of the master's
    occurrences. On Nextcloud (where we expand client-side) that showed the
    overridden day TWICE: the ghost the RRULE generates at the old time, plus
    the real overriding event at the new one. The ghost also read as busy, so a
    slot somebody had freed by moving that day still refused a booking."""
    overridden: dict[str, set[str]] = {}
    for event in events:
        if is_override(event):
            day = _day_digits(str(event.get(_OVERRIDE_FIELD, "")))
            if day:
                overridden.setdefault(event.get("UID", ""), set()).add(day)
    instances: list[dict[str, Any]] = []
    for event in events:
        if is_override(event):
            instances.append(event)
            continue
        replaced = overridden.get(event.get("UID", ""), set())
        instances.extend(
            instance
            for instance in expand_recurring(event, window_start_utc, window_end_utc)
            if _day_digits(str(instance.get("DTSTART", ""))) not in replaced
        )
    return instances


def in_window(events: list[dict[str, Any]], window_start_utc: str, window_end_utc: str) -> list[dict[str, Any]]:
    """The events that overlap [window_start_utc, window_end_utc), in order.

    A time-range REPORT is the server's filter, and iCloud's is loose: it can
    return a birthday on the day before a window opens, and a
    brief would list it as today's. So the window is checked here, on
    every backend. An event whose span cannot be read is kept, never silently
    dropped.
    """
    window_start = _dt.datetime.strptime(window_start_utc, "%Y%m%dT%H%M%SZ").replace(tzinfo=_dt.timezone.utc)
    window_end = _dt.datetime.strptime(window_end_utc, "%Y%m%dT%H%M%SZ").replace(tzinfo=_dt.timezone.utc)
    kept: list[dict[str, Any]] = []
    for event in events:
        start, end = event_span(event)
        if start is None or end is None or (start < window_end and end > window_start):
            kept.append(event)
    return kept


def _xml_escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def uid_query(uid: str) -> bytes:
    """calendar-query REPORT body selecting the one VEVENT with this UID. Used
    to find an event's resource href when we did not create it (its filename
    need not equal the UID, unlike assistant's own `<uid>.ics`).

    Asks for `calendar-data` as well as the etag so the CALLER can verify the
    UID in what came back. Not every server honours a UID prop-filter: Google
    answers this query with its whole collection, so a response is not proof of
    a match, and without the data there is nothing to check it against.
    """
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">\n'
        "  <D:prop><D:getetag/><C:calendar-data/></D:prop>\n"
        "  <C:filter><C:comp-filter name=\"VCALENDAR\">\n"
        "    <C:comp-filter name=\"VEVENT\">\n"
        f'      <C:prop-filter name="UID"><C:text-match>{_xml_escape(uid)}</C:text-match></C:prop-filter>\n'
        "    </C:comp-filter>\n"
        "  </C:comp-filter></C:filter>\n"
        "</C:calendar-query>\n"
    ).encode()


def multiget_query(href: str) -> bytes:
    """calendar-multiget REPORT body for ONE resource by its server path,
    asking for its etag and data.

    The direct `<uid>.ics` GET finds the assistant's own events but cannot see the
    ETag header (`dav_request` returns status and text only), so a write after
    it would go out with `If-Match: *`, and iCloud can answer a move of an
    event that is plainly there with 412. A multiget is the read every
    CalDAV client syncs with, iCloud included, and its multistatus carries the
    etag beside the data, so `etag_for_uid` reads it the same way it reads a
    calendar-query."""
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<C:calendar-multiget xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">\n'
        "  <D:prop><D:getetag/><C:calendar-data/></D:prop>\n"
        f"  <D:href>{_xml_escape(href)}</D:href>\n"
        "</C:calendar-multiget>\n"
    ).encode()


def holds_uid(text: str, uid: str) -> bool:
    """Whether `text` carries exactly this UID, as an iCalendar property.

    Matches the WHOLE value, not a substring: `UID:assistant-call` sits inside
    `UID:assistant-call-2`, so a containment test hands back the wrong event, which
    is the failure this lookup path exists to prevent. The value ends at
    a line break or at `<`, so this reads both a plain VEVENT and one embedded
    in a multistatus `calendar-data` element; the left guard keeps `X-ALT-UID:`
    and friends from passing as `UID:`."""
    return re.search(rf"(?<![A-Za-z0-9-])UID:{re.escape(uid)}(?=[\r\n<]|$)", unfold(text)) is not None


def _uid_chunk(multistatus_xml: str, uid: str) -> str | None:
    """The ONE <response> element of a multistatus whose calendar-data carries
    this UID, unescaped, or None. The href and the etag are both read out of
    this same chunk, so they can never be crossed between two events."""
    text = (
        multistatus_xml.replace("&#13;", "")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
    )
    for chunk in re.split(r"</[a-z]*:?response>", text, flags=re.IGNORECASE):
        if holds_uid(chunk, uid):
            return chunk
    return None


def href_for_uid(multistatus_xml: str, uid: str) -> str | None:
    """The href of the <response> whose calendar-data holds this UID. iCloud
    rejects a UID prop-filter REPORT (412), so we scan a time-range REPORT's
    results and match the UID in the returned VEVENT data ourselves. A response
    that does not carry the UID is not a match, however few responses came
    back: a server may ignore the filter entirely."""
    chunk = _uid_chunk(multistatus_xml, uid)
    if chunk is None:
        return None
    match = re.search(r"<[a-z]*:?href[^>]*>(.*?)</[a-z]*:?href>", chunk, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else None


def etag_for_uid(multistatus_xml: str, uid: str) -> str | None:
    """The getetag of that same <response>: the version token a conditional
    write quotes back in `If-Match`, so a PUT that would land on top of an edit
    somebody made in their own client is refused (412) instead.

    `uid_query` has always asked for `getetag`; nothing parsed it, so every
    read-modify-write here wrote unconditionally. Returned verbatim, quotes
    included, because a server compares the token exactly as it gave it."""
    chunk = _uid_chunk(multistatus_xml, uid)
    if chunk is None:
        return None
    match = re.search(r"<[a-z]*:?getetag[^>]*>(.*?)</[a-z]*:?getetag>", chunk, re.IGNORECASE | re.DOTALL)
    value = match.group(1).strip() if match else ""
    return value or None


def if_match(etag: str | None) -> dict[str, str]:
    """The conditional header for a read-modify-write PUT.

    `*` only when the lookup produced no etag at all: the direct-GET path
    (`<uid>.ics`, the assistant's own events) now asks a `multiget_query` for one, and
    falls back here when that read fails. `*` proves only that the resource
    still exists, not that it is unchanged; an etag proves both."""
    cleaned = (etag or "").strip()
    return {"If-Match": cleaned or "*"}


def human_local(utc_basic: str) -> str:
    """A UTC-basic time ('20260711T140000Z') as a local wall-clock string
    a person reads ('Sat 11 Jul 16:00'). For the citeable receipt so the model
    quotes the real local time back verbatim instead of restating a guess."""
    try:
        moment = _dt.datetime.strptime(utc_basic, "%Y%m%dT%H%M%SZ").replace(tzinfo=_dt.timezone.utc)
    except ValueError:
        return utc_basic
    return moment.astimezone(_LOCAL_TZ).strftime("%a %d %b %H:%M")


def human_range(start_utc: str, end_utc: str) -> str:
    """'Sat 11 Jul 16:00-16:30 (local)' from two UTC-basic times."""
    end_time = ""
    try:
        end = _dt.datetime.strptime(end_utc, "%Y%m%dT%H%M%SZ").replace(tzinfo=_dt.timezone.utc)
        end_time = end.astimezone(_LOCAL_TZ).strftime("%H:%M")
    except ValueError:
        end_time = end_utc
    return f"{human_local(start_utc)}-{end_time} (local time)"


def occurrence_date(value: str) -> str | None:
    """Normalise a date the person named ('2026-07-13', '2026-07-13 09:00',
    '20260713') to iCalendar basic date 'YYYYMMDD', or None if it has no
    plausible date. The time-of-day is taken from the master DTSTART, not here,
    so only the date matters for picking which occurrence to cancel."""
    digits = re.sub(r"\D", "", value)[:8]
    if len(digits) != 8:
        return None
    try:
        _dt.datetime.strptime(digits, "%Y%m%d")
    except ValueError:
        return None
    return digits


def is_override(event: dict[str, Any]) -> bool:
    """Whether this VEVENT REPLACES one occurrence of a series rather than
    being the series master or a plain event: it carries a RECURRENCE-ID naming
    the instance it stands in for. Any human client writes one of these the
    moment somebody drags a single day of a repeating meeting."""
    return bool(str(event.get(_OVERRIDE_FIELD, "")).strip())


def master_event(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The master of a parsed resource: the first event that is not an
    override, so a receipt names the series rather than the one day somebody
    moved. Falls back to the first event when every one is an override, and
    None when there are none at all."""
    for event in events:
        if not is_override(event):
            return event
    return events[0] if events else None


def _property_name(line: str) -> str:
    """The upper-case property name of an unfolded iCalendar line
    ('RECURRENCE-ID;TZID=Europe/local:2026...' -> 'RECURRENCE-ID')."""
    return line.strip().upper().split(";")[0].split(":")[0]


def _vevent_spans(lines: list[str]) -> list[tuple[int, int]]:
    """(begin, end) index pairs, one per VEVENT component in `lines`, the
    BEGIN and END lines included. VEVENTs never nest, so no stack is needed."""
    spans: list[tuple[int, int]] = []
    begin: int | None = None
    for index, line in enumerate(lines):
        stripped = line.strip().upper()
        if stripped == "BEGIN:VEVENT":
            begin = index
        elif stripped == "END:VEVENT" and begin is not None:
            spans.append((begin, index))
            begin = None
    return spans


def _master_span(lines: list[str]) -> tuple[int, int] | None:
    """The line span of the MASTER VEVENT: the one component carrying no
    RECURRENCE-ID.

    Taking the FIRST VEVENT as the master is wrong: a resource whose series has
    an overridden occurrence holds that override as a second VEVENT which very
    often comes first. An EXDATE built from the override's time-of-day and
    spliced into the override's own component is ignored by the server, so a
    cancel would report success while the day stays on the calendar, and on the
    move-one-occurrence path the fresh booking would land on top of a day that
    never dropped out.

    Falls back to the first component when every one carries a RECURRENCE-ID
    (an override fetched on its own), so a caller always gets an answer."""
    spans = _vevent_spans(lines)
    if not spans:
        return None
    for first, last in spans:
        if not any(_property_name(line) == _OVERRIDE_FIELD for line in lines[first:last]):
            return first, last
    return spans[0]


def _nested_component_lines(lines: list[str], first: int, last: int) -> set[int]:
    """The indices between `first` and `last` that belong to a component NESTED
    inside the VEVENT (a VALARM) rather than to the event itself.

    A VALARM carries property names the event carries too: DESCRIPTION is
    required on a DISPLAY alarm, and a repeating alarm states its own DURATION.
    Without this, a splice aimed at the event reached into the alarm: updating
    a description deleted the alarm's, and updating one on an event that had
    none wrote the meeting's body inside the alarm and left the event with no
    description at all. Nothing else in a VEVENT nests, so a depth counter is
    the whole rule."""
    nested: set[int] = set()
    depth = 0
    for index in range(first + 1, last):
        stripped = lines[index].strip().upper()
        if stripped.startswith("BEGIN:"):
            depth += 1
        if depth:
            nested.add(index)
        if stripped.startswith("END:") and depth:
            depth -= 1
    return nested


def master_dtstart_line(ics_text: str) -> str | None:
    """The raw DTSTART line (with its params) of the MASTER VEVENT, unfolded:
    the anchor an EXDATE must match exactly on value-type and TZID."""
    lines = [line.strip() for line in unfold(ics_text).splitlines()]
    span = _master_span(lines)
    if span is None:
        return None
    first, last = span
    for line in lines[first:last]:
        if line.upper().startswith("DTSTART"):
            return line
    return None


def exdate_line(dtstart_line: str, occ_yyyymmdd: str) -> str | None:
    """Build the EXDATE line that cancels the `occ_yyyymmdd` occurrence of a
    series whose master DTSTART is `dtstart_line`. The value-type and TZID MUST
    match the master or the server ignores the exclusion, so the EXDATE reuses
    the master's params and time-of-day, only swapping in the target date."""
    prop, _, value = dtstart_line.partition(":")
    if not value:
        return None
    params = [p for p in prop.split(";")[1:] if p]
    is_date = any(p.upper() == "VALUE=DATE" for p in params) or (len(value) == 8 and value.isdigit())
    if is_date:
        return f"EXDATE;VALUE=DATE:{occ_yyyymmdd}"
    if "T" not in value:
        return None
    time_part = value.split("T", 1)[1]
    utc_suffix = "Z" if time_part.endswith("Z") else ""
    hms = time_part.rstrip("Z")
    keep = [p for p in params if p.upper().startswith("TZID=")]
    prefix = "EXDATE" + ("".join(f";{p}" for p in keep) if keep else "")
    return f"{prefix}:{occ_yyyymmdd}T{hms}{utc_suffix}"


def splice_exdate(ics_text: str, exdate: str) -> bytes:
    """Insert `exdate` into the MASTER VEVENT, just before its END:VEVENT, and
    return the whole calendar re-encoded. Lossless: every other line (RRULE,
    ALARMs, custom X- props, any RECURRENCE-ID override) is preserved, so the
    rest of the series is untouched. CRLF per RFC 5545."""
    lines = ics_text.replace("\r\n", "\n").split("\n")
    span = _master_span(lines)
    out = lines if span is None else lines[: span[1]] + [exdate] + lines[span[1] :]
    return "\r\n".join(line for line in out if line != "").encode() + b"\r\n"


def replace_times(ics_text: str, start_utc: str, end_utc: str) -> bytes:
    """Rewrite the first VEVENT's DTSTART/DTEND to `start_utc`/`end_utc` and
    return the whole calendar re-encoded, so an event MOVES in place instead of
    being deleted and re-added under a new id. Lossless like
    `splice_exdate`: SUMMARY, LOCATION, DESCRIPTION, alarms and custom props
    survive, and the UID is untouched, so every client follows the change
    rather than showing two events. Any DTSTART/DTEND params (TZID, VALUE=DATE)
    go with the old value, because the new one is plain UTC basic; a DURATION
    is dropped in favour of the explicit DTEND. The MASTER component is the one
    rewritten: on a series carrying an override, rewriting the override instead
    would leave its RECURRENCE-ID pointing at the old instance, which is a
    corrupt event rather than a moved one."""
    lines = ics_text.replace("\r\n", "\n").split("\n")
    span = _master_span(lines)
    if span is None:
        return "\r\n".join(line for line in lines if line != "").encode() + b"\r\n"
    first, last = span
    nested = _nested_component_lines(lines, first, last)
    out = list(lines[: first + 1])
    wrote_end = False
    for index in range(first + 1, last):
        line = lines[index]
        upper = line.strip().upper()
        if index in nested:
            out.append(line)  # a VALARM's own DURATION is not the event's length
        elif upper.startswith("DTSTART;") or upper.startswith("DTSTART:"):
            out.append(f"DTSTART:{start_utc}")
        elif upper.startswith("DTEND;") or upper.startswith("DTEND:"):
            out.append(f"DTEND:{end_utc}")
            wrote_end = True
        elif upper.startswith("DURATION;") or upper.startswith("DURATION:"):
            continue  # replaced by the explicit DTEND
        else:
            out.append(line)
    if not wrote_end:
        out.append(f"DTEND:{end_utc}")
    out += lines[last:]
    return "\r\n".join(line for line in out if line != "").encode() + b"\r\n"


def rrule_weekdays(rrule: str) -> list[str]:
    """The BYDAY tokens of a recurrence rule ('MO', 'TH'), upper-cased, in the
    rule's own order; empty when it names none.

    A weekly rule takes its WEEKDAY from BYDAY and only its time-of-day from
    DTSTART, which this module's own expander proves. So this is what decides
    whether a requested new start would actually move a series, or whether the
    rule would quietly win and the person would not get the move they asked
    for. An ordinal prefix ('2MO', the second Monday) still names Monday."""
    byday = _parse_rrule(rrule).get("BYDAY", "")
    return [token.strip().upper()[-2:] for token in byday.split(",") if token.strip()]


def weekday_token(utc_basic: str) -> str:
    """The BYDAY token of this instant in the owner's local time (ASSISTANT_TIMEZONE), which is the
    frame a person names a day in here. '' when the value cannot be read."""
    try:
        moment = _dt.datetime.strptime(utc_basic, "%Y%m%dT%H%M%SZ").replace(tzinfo=_dt.timezone.utc)
    except ValueError:
        return ""
    weekday = moment.astimezone(_LOCAL_TZ).weekday()
    return next((token for token, index in _WEEKDAY.items() if index == weekday), "")


def _value_like(params: list[str], old_value: str, utc_basic: str) -> str:
    """The new instant written the way the old value was written: a UTC-basic
    value stays UTC basic, a TZID value becomes that zone's wall clock, an
    all-day DATE becomes a date, a bare value stays bare local."""
    try:
        instant = _dt.datetime.strptime(utc_basic, "%Y%m%dT%H%M%SZ").replace(tzinfo=_dt.timezone.utc)
    except ValueError:
        return utc_basic
    if any(param.upper() == "VALUE=DATE" for param in params) or (len(old_value) == 8 and old_value.isdigit()):
        return instant.astimezone(_LOCAL_TZ).strftime("%Y%m%d")
    tzid = next((param.split("=", 1)[1].strip() for param in params if param.upper().startswith("TZID=")), "")
    if tzid:
        try:
            zone: _dt.tzinfo = ZoneInfo(tzid)
        except Exception:  # noqa: BLE001 - an unknown zone falls back, never raises
            zone = _LOCAL_TZ
        return instant.astimezone(zone).strftime("%Y%m%dT%H%M%S")
    if old_value.endswith("Z"):
        return utc_basic
    return instant.astimezone(_LOCAL_TZ).strftime("%Y%m%dT%H%M%S")


def _retimed_line(property_line: str, utc_basic: str) -> str:
    """One DTSTART/DTEND line keeping its property name and every param, with a
    new instant written in the representation that line already used."""
    prop, _, old_value = property_line.partition(":")
    params = [param for param in prop.split(";")[1:] if param]
    return f"{prop}:{_value_like(params, old_value.strip(), utc_basic)}"


def shift_series(ics_text: str, start_utc: str, end_utc: str) -> bytes:
    """Move a WHOLE series: rewrite the master's DTSTART (and its DTEND, when
    it has one) to the new instants, each written in the representation that
    line already used, and leave the RRULE and every other line untouched.

    Deliberately NOT `replace_times`, which writes plain UTC and drops TZID.
    A wall-clock series anchored to Europe/local would then keep one fixed
    UTC offset across the DST change and start an hour wrong for half the year,
    on every future occurrence, on everybody's phone. A master that expresses
    its length as a DURATION keeps it, so the length follows the new start
    instead of standing beside a contradicting DTEND."""
    lines = ics_text.replace("\r\n", "\n").split("\n")
    span = _master_span(lines)
    if span is None:
        return "\r\n".join(line for line in lines if line != "").encode() + b"\r\n"
    first, last = span
    nested = _nested_component_lines(lines, first, last)
    out = list(lines[: first + 1])
    wrote_end = False
    has_duration = False
    for index in range(first + 1, last):
        line = lines[index]
        stripped = line.strip()
        upper = stripped.upper()
        if index in nested:
            out.append(line)  # a repeating VALARM's DURATION says nothing about the event
        elif upper.startswith("DTSTART;") or upper.startswith("DTSTART:"):
            out.append(_retimed_line(stripped, start_utc))
        elif upper.startswith("DTEND;") or upper.startswith("DTEND:"):
            out.append(_retimed_line(stripped, end_utc))
            wrote_end = True
        else:
            has_duration = has_duration or upper.startswith("DURATION;") or upper.startswith("DURATION:")
            out.append(line)
    if not wrote_end and not has_duration:
        out.append(f"DTEND:{end_utc}")
    out += lines[last:]
    return "\r\n".join(line for line in out if line != "").encode() + b"\r\n"


def _property_line(name: str, value: str) -> str:
    """One iCalendar property line with no params. TEXT values are escaped
    through `ical_text`; structured ones never are, because escaping an RRULE's
    own semicolons stops the rule parsing at all."""
    return f"{name}:{ical_text(value) if name in _TEXT_PROPERTIES else value}"


def splice_properties(ics_text: str, values: dict[str, str], drop: list[str] | tuple[str, ...] = ()) -> bytes:
    """Rewrite the named properties inside the MASTER VEVENT, remove the ones
    named in `drop`, and leave every other line byte for byte, returning the
    whole calendar re-encoded.

    `build_event` is the wrong tool for an edit: it writes a minimal VEVENT
    from scratch, so changing a title through it silently drops the alarm
    somebody set, the attendee list, the call link and every X- property their
    client keeps. This replaces a named property's whole line (its old params
    go with its old value, exactly as `replace_times` does, because the new
    value carries no zone) together with any folded continuation of it, appends
    a property that was not there before just above END:VEVENT, and touches
    nothing else. Writing a DTEND drops a DURATION, which RFC 5545 forbids
    beside it. A dropped property goes with its folded continuation, and only
    from the master itself: an alarm's own DESCRIPTION stays with the alarm."""
    wanted = {name.upper(): value for name, value in values.items()}
    removed = {name.upper() for name in drop}
    lines = ics_text.replace("\r\n", "\n").split("\n")
    span = _master_span(lines)
    if span is None or not (wanted or removed):
        return "\r\n".join(line for line in lines if line != "").encode() + b"\r\n"
    first, last = span
    nested = _nested_component_lines(lines, first, last)
    out = list(lines[: first + 1])
    written: set[str] = set()
    dropping = False
    for index in range(first + 1, last):
        line = lines[index]
        if line[:1] in (" ", "\t"):
            if not dropping:
                out.append(line)
            continue
        dropping = False
        if index in nested:
            out.append(line)  # the alarm's DESCRIPTION belongs to the alarm
            continue
        name = _property_name(line)
        if name in wanted:
            if name not in written:
                out.append(_property_line(name, wanted[name]))
                written.add(name)
            dropping = True
            continue
        if name in removed or (name == "DURATION" and "DTEND" in wanted):
            dropping = True
            continue
        out.append(line)
    out += [_property_line(name, value) for name, value in wanted.items() if name not in written]
    out += lines[last:]
    return "\r\n".join(line for line in out if line != "").encode() + b"\r\n"


def text_property(ics_text: str, name: str) -> str:
    """The unescaped value of TEXT property `name` in the MASTER VEVENT, or ''.

    Reads back what `ical_text` wrote, so a value can be carried from one event
    into a new one (moving a single occurrence out of a series keeps its title
    and its call link) without the escaping accumulating a backslash each pass.
    Reading the master rather than the first component keeps a series that
    somebody once dragged one day of from re-booking under the override's
    title ('Standup (verplaatst)').
    """
    lines = [line.strip() for line in unfold(ics_text).splitlines()]
    span = _master_span(lines)
    if span is None:
        return ""
    first, last = span
    nested = _nested_component_lines(lines, first, last)
    for index in range(first + 1, last):
        line = lines[index]
        if index in nested:
            continue  # a DISPLAY alarm's DESCRIPTION is the reminder, not the event body
        if _property_name(line) == name.upper():
            _, _, value = line.partition(":")
            return (
                value.replace("\\n", "\n")
                .replace("\\N", "\n")
                .replace("\\,", ",")
                .replace("\\;", ";")
                .replace("\\\\", "\\")
            )
    return ""


def wide_window() -> tuple[str, str]:
    """A broad UTC-basic [start, end) for locating an event by UID when we do
    not know its date: from ~a month back to ~13 months ahead, which covers
    virtually every event a person asks to touch."""
    now = _dt.datetime.now(_dt.timezone.utc)
    start = (now - _dt.timedelta(days=31)).strftime("%Y%m%dT%H%M%SZ")
    end = (now + _dt.timedelta(days=400)).strftime("%Y%m%dT%H%M%SZ")
    return start, end
