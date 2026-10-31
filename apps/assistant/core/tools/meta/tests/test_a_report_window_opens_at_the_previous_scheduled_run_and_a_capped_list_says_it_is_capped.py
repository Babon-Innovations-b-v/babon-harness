"""A report's change window opens at its previous scheduled run, and a list
cut at its cap says it is cut.

WHAT IT PINS. `whats_changed.report_window_start` and `whats_changed.execute`
at the tool seam, plus `changes.digest_since` with `changes._run_gh` (its one
subprocess seam) replaced. Morning: the previous weekday 08:00 local, so
Monday reaches back to Friday. Weekly: the previous Monday 09:00. An unknown
kind is a FAILED result, never a silent 24 hours. `REPORT_SCHEDULES` matches
the gateway's two automations. A commit list longer than the cap says MORE
EXIST and does not print a bare count.

WHY IT EXISTS. A window read from a stored marker whose only writer is gone
stays frozen at an old date, and a capped list without a word about the cap
reads as complete; a report with no marker silently gets 24 hours.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The dates are
read off a calendar: 2026-10-06 is a Tuesday, 2026-10-02 a Friday, and
local is UTC+2 in early October (CEST until 25 October), so 08:00 local is
06:00Z and 09:00 local is 07:00Z. The schedule is checked against the cron
strings in `workspace/gateway_automations.json`, read as data.
"""
from __future__ import annotations

from apps.assistant.workspace import fragment

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from apps.assistant.core import changes
from apps.assistant.core.tools.meta import result, whats_changed



def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


@pytest.mark.parametrize(
    ("kind", "now", "expected"),
    [
        # Tuesday 08:00:30 local: the window opens Monday 08:00.
        ("morning", "2026-10-06T06:00:30Z", "2026-10-05T06:00:00Z"),
        # Monday 08:30 local: the window reaches back to Friday 08:00.
        ("morning", "2026-10-05T06:30:00Z", "2026-10-02T06:00:00Z"),
        # Monday 09:00:30 local: exactly one week back.
        ("weekly", "2026-10-05T07:00:30Z", "2026-09-28T07:00:00Z"),
    ],
)
def test_the_window_opens_at_the_run_before_the_latest(kind: str, now: str, expected: str) -> None:
    """Each report looks back to the scheduled run before the current one."""
    assert whats_changed.report_window_start(kind, _utc(now)) == _utc(expected)


def test_an_unknown_kind_fails_instead_of_falling_back_to_a_day() -> None:
    """A kind with no schedule is an error naming the valid kinds."""
    with pytest.raises(ValueError):
        whats_changed.report_window_start("evening", _utc("2026-10-06T06:00:30Z"))
    outcome = whats_changed.execute({"report_kind": "evening"})
    assert isinstance(outcome, result.ToolResult)
    assert outcome.status == result.FAILED
    assert "morning" in outcome.error and "weekly" in outcome.error


def test_the_morning_window_never_reaches_back_a_month(monkeypatch: pytest.MonkeyPatch) -> None:
    """Through the tool seam, the morning window is at most four days wide
    (Monday before 08:00 reaches Thursday 08:00), whatever is in the state DB."""
    seen: list[str] = []
    monkeypatch.setattr(changes, "digest_since", lambda since: seen.append(since) or "")
    whats_changed.execute({"report_kind": "morning"})
    width = datetime.now(timezone.utc) - _utc(seen[0])
    assert 0 < width.total_seconds() <= 4 * 86400 + 3600


def _cron_fields(cron: str) -> tuple[int, int, frozenset[int]]:
    """(minute, hour, Python weekdays) from a `M H * * DOW` cron line."""
    minute, hour, _day, _month, dow = cron.split()
    days: set[int] = set()
    for part in dow.split(","):
        first, _, last = part.partition("-")
        days.update(range(int(first), int(last or first) + 1))
    # cron numbers Sunday 0 and Monday 1; Python numbers Monday 0.
    return int(minute), int(hour), frozenset((day - 1) % 7 for day in days)


def test_the_schedule_matches_the_gateway_automations() -> None:
    """The constant the tool uses is the cron the gateway runs."""
    declared = fragment.render_automations()["automations"]
    by_key = {entry["declarationKey"]: entry for entry in declared}
    for kind, key in (("morning", "harness:morning-brief"), ("weekly", "harness:weekly-advisor")):
        schedule = whats_changed.REPORT_SCHEDULES[kind]
        minute, hour, weekdays = _cron_fields(by_key[key]["cron"])
        assert (schedule.minute, schedule.hour, schedule.weekdays) == (minute, hour, weekdays)
        assert schedule.zone == by_key[key]["tz"]


def test_a_commit_list_past_the_cap_says_more_exist(monkeypatch: pytest.MonkeyPatch) -> None:
    """Forty-one commits from gh render as 40 shown and MORE EXIST, never a
    bare count of 40."""
    commit_rows = "\n".join(
        json.dumps({"sha": f"{index:010d}", "message": f"commit {index}",
                    "at": f"2026-10-0{1 + index % 5}T10:00:00Z"})
        for index in range(41)
    )

    def _gh(args: list[str]) -> tuple[int, str, str]:
        return (0, commit_rows, "") if args[0] == "api" else (0, "[]", "")

    monkeypatch.setattr(changes, "_run_gh", _gh)
    digest = changes.digest_since("2026-09-07T06:00:22Z")
    assert "MORE EXIST" in digest
    assert "Commits on main (40" not in digest
    assert digest.count("\n- ") == 40
    assert "days" in digest.splitlines()[0]
