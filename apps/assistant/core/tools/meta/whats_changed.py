"""Read-only `whats_changed` tool, the change-feed as a tool.

Wraps `core.changes.digest_since` so any loop can ask "what actually landed
and which issues moved" since a point in time, and ground its answer in the
record instead of memory. Reports pass a `report_kind`; chat can pass a
`since_iso` or just take the default 24-hour window.

A report's window is WORKED OUT FROM ITS SCHEDULE, never read from a stored
marker. A stored marker whose only writer is gone stays frozen at an old
date, and a report with no marker silently gets a default window. A window computed from the cron cannot go stale. `REPORT_SCHEDULES`
mirrors the two gateway automations in `workspace/gateway_automations.json`
(the container image does not ship that file); a test pins the two together.

Tool-module grammar: NAME, DEFINITION, execute. Read-only (queries GitHub),
so it lives in the shared registry.
"""
from __future__ import annotations

from apps.assistant.shared.zone import LOCAL_ZONE_NAME

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from apps.assistant.core import changes
from apps.assistant.core.tools.meta import result

NAME = "whats_changed"

_DEFAULT_WINDOW_HOURS = 24


@dataclass(frozen=True)
class ReportSchedule:
    """When one report runs: a local wall-clock time on some weekdays
    (Python numbering, Monday = 0)."""

    hour: int
    minute: int
    weekdays: frozenset[int]
    zone: str = LOCAL_ZONE_NAME


def _clock(env_name: str, default: str) -> tuple[int, int]:
    """(hour, minute) from an `HH:MM` setting, the same one the gateway's
    cron is rendered from (`workspace/fragment.py`)."""
    raw = os.environ.get(env_name, "").strip() or default
    hour, _, minute = raw.partition(":")
    return int(hour), int(minute)


_BRIEF = _clock("ASSISTANT_BRIEF_TIME", "08:00")
_ADVISOR = _clock("ASSISTANT_ADVISOR_TIME", "09:00")

# The gateway's `harness:morning-brief` (weekdays) and `harness:weekly-advisor`
# (Mondays), both on the owner's local zone.
REPORT_SCHEDULES: dict[str, ReportSchedule] = {
    "morning": ReportSchedule(hour=_BRIEF[0], minute=_BRIEF[1], weekdays=frozenset(range(5))),
    "weekly": ReportSchedule(hour=_ADVISOR[0], minute=_ADVISOR[1], weekdays=frozenset({0})),
}


DEFINITION: dict[str, Any] = {
    "name": NAME,
    "description": (
        "Commits on main and issues created or changed since a point in time. "
        "Use it before a report: report_kind gives that report's window, else "
        "since_iso, else the last 24 hours."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "report_kind": {
                "type": "string",
                "enum": sorted(REPORT_SCHEDULES),
                "description": (
                    "morning: since the previous weekday brief; "
                    "weekly: since the previous Monday advisor run."
                ),
            },
            "since_iso": {"type": "string", "description": "ISO8601 UTC."},
        },
        "required": [],
    },
}


def _scheduled_runs_before(schedule: ReportSchedule, moment: datetime, count: int) -> list[datetime]:
    """The `count` most recent scheduled runs at or before `moment`, newest first."""
    zone = ZoneInfo(schedule.zone)
    local = moment.astimezone(zone)
    runs: list[datetime] = []
    day = local.date()
    while len(runs) < count:
        if day.weekday() in schedule.weekdays:
            run = datetime(day.year, day.month, day.day, schedule.hour, schedule.minute, tzinfo=zone)
            if run <= local:
                runs.append(run)
        day -= timedelta(days=1)
    return runs


def report_window_start(report_kind: str, now: datetime) -> datetime:
    """Where `report_kind`'s window opens: the scheduled run BEFORE the latest
    one at or before `now`. Raises ValueError for a kind with no schedule."""
    schedule = REPORT_SCHEDULES.get(report_kind.strip().lower())
    if schedule is None:
        raise ValueError(
            f"unknown report_kind {report_kind!r}; valid kinds: {', '.join(sorted(REPORT_SCHEDULES))}"
        )
    return _scheduled_runs_before(schedule, now, 2)[1].astimezone(timezone.utc)


def _iso(moment: datetime) -> str:
    """`moment` as ISO8601 UTC with seconds precision."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def execute(tool_input: dict[str, Any]) -> str | result.ToolResult:
    since = str(tool_input.get("since_iso", "")).strip()
    kind = str(tool_input.get("report_kind", "")).strip()
    now = datetime.now(timezone.utc)
    if not since and kind:
        try:
            since = _iso(report_window_start(kind, now))
        except ValueError as exc:
            return result.failed(NAME, str(exc))
    if not since:
        since = _iso(now - timedelta(hours=_DEFAULT_WINDOW_HOURS))
    return changes.digest_since(since)
