"""Quiet hours, the assistant does not start conversations at night.

An assistant left to itself will message people in the middle of the night
about things that are not urgent. The
rule: between 22:00 and 07:30 local time the assistant sends no UNSOLICITED
Signal, no patrol lines, no own-initiative teammate messages. Everything
reactive stays: chat replies (the person is awake, they just messaged),
human-driven teammate messages (their call, their responsibility), real
pages (the paging path never consults this), and the timer beats that live
outside the window anyway (the weekday morning brief at 08:00).

`quiet_now(now=None) -> bool`, True while the quiet window is active.
Window from ``ASSISTANT_QUIET_HOURS`` ("HH:MM-HH:MM", may wrap midnight;
"off" disables; unset means the 22:00-07:30 default; malformed falls back
to the default, logged). Clock is Europe/local unless an aware `now`
is passed (tests pass one).

FAILURE POLICY: pure clock arithmetic. Any error reads as NOT quiet, so a
broken config can never silence the assistant during the day.
"""
from __future__ import annotations

from apps.assistant.shared.zone import LOCAL_ZONE

import datetime as _dt
import logging
import os
import re
from zoneinfo import ZoneInfo

log = logging.getLogger("openclaw.quiet_hours")

_ENV = "ASSISTANT_QUIET_HOURS"
_DEFAULT_WINDOW = "22:00-07:30"
_OFF_VALUES = {"off", "none", "0", "false"}
_WINDOW_RE = re.compile(r"^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$")
_TZ = LOCAL_ZONE


def _window_minutes(raw: str) -> tuple[int, int] | None:
    """"HH:MM-HH:MM" -> (start, end) as minutes-since-midnight, or None."""
    match = _WINDOW_RE.match(raw.strip())
    if not match:
        return None
    start_h, start_m, end_h, end_m = (int(group) for group in match.groups())
    if start_h > 23 or end_h > 23 or start_m > 59 or end_m > 59:
        return None
    return start_h * 60 + start_m, end_h * 60 + end_m


def ends_at_minute() -> int | None:
    """Minutes since local midnight at which the quiet window ends, or None
    when quiet hours are switched off.

    `page_hold` needs this to know where the morning begins. It could not read
    it off `quiet_now`, which answers a yes or no about one instant and says
    nothing about where the boundary is, and a second copy of the window in
    another module is two clocks that drift. Same env, same default,
    same malformed-falls-back-to-the-default rule, so the two answers cannot
    disagree about the same configuration.
    """
    raw = os.environ.get(_ENV, _DEFAULT_WINDOW).strip()
    if raw.lower() in _OFF_VALUES or raw == "":
        return None
    window = _window_minutes(raw) or _window_minutes(_DEFAULT_WINDOW)
    return window[1] if window else None


def local_moment(now: _dt.datetime | None = None) -> _dt.datetime:
    """`now` (or this moment) on the local clock the window is read on.

    For a caller that needs the local date or weekday as well as the minute,
    so it does not declare a second copy of the zone (see `local_minute`).
    """
    moment = now if now is not None else _dt.datetime.now(_TZ)
    return moment.astimezone(_TZ)


def local_minute(now: _dt.datetime | None = None) -> int:
    """Minutes since local midnight, on the same clock the window is read on.

    Exposed so a caller comparing an instant against `ends_at_minute` uses this
    module's zone rather than declaring a second one. Two modules holding their
    own copy of Europe/local agree until the day one of them is changed.
    """
    moment = now if now is not None else _dt.datetime.now(_TZ)
    local = moment.astimezone(_TZ)
    return local.hour * 60 + local.minute


def quiet_now(now: _dt.datetime | None = None) -> bool:
    """True while unsolicited sends should hold (see module docstring)."""
    try:
        raw = os.environ.get(_ENV, _DEFAULT_WINDOW).strip()
        if raw.lower() in _OFF_VALUES or raw == "":
            return False
        window = _window_minutes(raw)
        if window is None:
            log.warning("malformed %s=%r; using default %s", _ENV, raw, _DEFAULT_WINDOW)
            window = _window_minutes(_DEFAULT_WINDOW)
        start, end = window
        moment = now if now is not None else _dt.datetime.now(_TZ)
        minute = moment.astimezone(_TZ).hour * 60 + moment.astimezone(_TZ).minute
        if start <= end:
            return start <= minute < end
        return minute >= start or minute < end  # window wraps midnight
    except Exception as exc:  # noqa: BLE001, never silence the assistant on a config fault
        log.warning("quiet_now errored (%s); treating as not quiet", exc)
        return False
