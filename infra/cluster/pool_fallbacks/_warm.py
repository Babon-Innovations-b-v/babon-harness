"""How many gate nodes stay up in working hours, and the two cron lines that move it.

OWNS: turning `POOL_GATE_WARM`, `POOL_GATE_MIN`, `WORKING_DAYS` and
`WORKING_HOURS` into the warm floor: the node count in working hours, the
count outside them, and the cron schedule of the CronJobs that switch between
the two (`infra/k8s/deploy/gate-warm.yaml`, read in `ASSISTANT_TIMEZONE`).
DOES NOT OWN: the pools themselves (`_pools.py`) or what keeps a node up
(the `gate-warm` Deployment).

`WORKING_DAYS` is a range (`Mon-Fri`) or a list (`Mon,Wed,Fri`) of three-letter
day names; `WORKING_HOURS` is `HH:MM-HH:MM`, the end after the start, on one
day. `POOL_GATE_WARM` empty or 0 means no warm floor at all.

FAILURE POLICY: Tier 1 loud, like the pools. A malformed line raises
ValueError naming its key; a wrong schedule would bill nodes nobody uses.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

_DAYS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")


@dataclass(frozen=True)
class WarmFloor:
    """Gate nodes kept up in working hours and outside them, and the cron lines between."""

    working: int
    idle: int
    up: str
    down: str
    #: Cron day numbers (Sunday 0) and the (hour, minute) the hours open and close.
    days: frozenset[int] = frozenset()
    opens: tuple[int, int] = (0, 0)
    closes: tuple[int, int] = (0, 0)

    def count_at(self, weekday: int, hour: int, minute: int) -> int:
        """The node count the floor asks for at that moment; `weekday` is cron's (Sunday 0)."""
        inside = weekday in self.days and self.opens <= (hour, minute) < self.closes
        return self.working if inside else self.idle


def _day(name: str) -> int:
    """'Mon' -> 1, cron's day of week, or ValueError naming WORKING_DAYS."""
    try:
        return _DAYS.index(name.strip().capitalize())
    except ValueError:
        raise ValueError(f"WORKING_DAYS names {name!r}, not one of {', '.join(_DAYS)}") from None


def _days(value: str) -> tuple[str, frozenset[int]]:
    """'Mon-Fri' -> ('1-5', {1..5}), 'Mon,Wed' -> ('1,3', {1, 3})."""
    value = value.strip()
    if not value:
        raise ValueError("WORKING_DAYS is empty in config/harness.env")
    if "-" in value:
        first, _, last = value.partition("-")
        start, end = _day(first), _day(last)
        if end < start:
            raise ValueError(f"WORKING_DAYS={value!r} runs backwards")
        return f"{start}-{end}", frozenset(range(start, end + 1))
    numbers = [_day(name) for name in value.split(",")]
    return ",".join(str(number) for number in numbers), frozenset(numbers)


def _clock(value: str) -> tuple[int, int]:
    """'08:30' -> (8, 30), or ValueError naming WORKING_HOURS."""
    hour, colon, minute = value.strip().partition(":")
    if not (colon and hour.isdigit() and minute.isdigit() and int(hour) < 24 and int(minute) < 60):
        raise ValueError(f"WORKING_HOURS has {value!r}, not HH:MM")
    return int(hour), int(minute)


def warm_floor(settings: Mapping[str, str]) -> WarmFloor | None:
    """The gate role's warm floor, or None when `POOL_GATE_WARM` is empty or 0."""
    raw = (settings.get("POOL_GATE_WARM") or "0").strip()
    if not raw.isdigit():
        raise ValueError(f"POOL_GATE_WARM={raw!r} is not a whole number")
    if int(raw) == 0:
        return None
    idle = (settings.get("POOL_GATE_MIN") or "0").strip()
    if not idle.isdigit():
        raise ValueError(f"POOL_GATE_MIN={idle!r} is not a whole number")
    days, day_set = _days(settings.get("WORKING_DAYS") or "")
    opens, _, closes = (settings.get("WORKING_HOURS") or "").partition("-")
    (open_hour, open_minute), (close_hour, close_minute) = _clock(opens), _clock(closes)
    if (close_hour, close_minute) <= (open_hour, open_minute):
        raise ValueError(f"WORKING_HOURS={settings.get('WORKING_HOURS')!r} ends before it starts")
    return WarmFloor(
        working=int(raw),
        idle=int(idle),
        up=f"{open_minute} {open_hour} * * {days}",
        down=f"{close_minute} {close_hour} * * {days}",
        days=day_set,
        opens=(open_hour, open_minute),
        closes=(close_hour, close_minute),
    )
