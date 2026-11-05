"""A check is dispatched by its kind, and a heartbeat is up only inside its window and unknown before its first beat.

WHAT IT PINS. `monitor.checks.run_check`, the registry the sweep calls: a kind
it has no check for answers `unknown` instead of raising, and the push-only
`heartbeat` check reads the last beat off the prior status row: inside
`max_staleness_s` it is up, past it down, a beat never seen is unknown (so a
sender not wired yet never pages), and a stamp it cannot parse is down.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The clock is the
suite's frozen instant (`FROZEN_AT`), and each made-up beat is placed by hand a
known number of seconds before it against a window of 600 seconds: 60 seconds
old is inside, 3,600 is past.

ONE FUNCTION. This module's one test. A new check is a parametrized case of
it, never a second function.

WHAT IT WAS PROVED AGAINST. The break in this test's register row turns the
window around, so a fresh beat reads down and an overdue one up.

GUARDS. One test per module (#1210), 2026-11-05.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from apps.assistant.conftest import FROZEN_AT
from apps.assistant.core.monitor.checks import run_check
from apps.assistant.core.monitor.component import KIND_HEARTBEAT, Component


def _component(kind: str = KIND_HEARTBEAT) -> Component:
    return Component("nightly-backup", "data", kind, "", 600, True)


def _beat(seconds_ago: int) -> dict:
    return {"last_ok_at": (FROZEN_AT - timedelta(seconds=seconds_ago)).isoformat()}


CASES = [
    pytest.param(KIND_HEARTBEAT, _beat(60), "up", id="a-beat-inside-the-window"),
    pytest.param(KIND_HEARTBEAT, _beat(3600), "down", id="a-beat-past-the-window"),
    pytest.param(KIND_HEARTBEAT, None, "unknown", id="never-beaten-is-unknown-not-down"),
    pytest.param(KIND_HEARTBEAT, {"last_ok_at": ""}, "unknown", id="an-empty-stamp-is-never-seen"),
    pytest.param(KIND_HEARTBEAT, {"last_ok_at": "yesterday-ish"}, "down", id="an-unreadable-stamp"),
    pytest.param("carrier-pigeon", None, "unknown", id="a-kind-with-no-check"),
]


@pytest.mark.parametrize("kind, prior_row, expected", CASES)
def test_a_check_is_dispatched_by_its_kind_and_a_heartbeat_is_up_only_inside_its_window_and_unknown_before_its_first_beat(
        kind: str, prior_row: dict | None, expected: str, frozen_clock) -> None:
    """The classification is the hand-placed one."""
    assert run_check(_component(kind), prior_row).classification == expected
