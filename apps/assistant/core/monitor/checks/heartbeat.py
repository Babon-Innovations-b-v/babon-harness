"""`heartbeat` check: up iff `last_ok_at` is within max-staleness.

Push-only. There is no active probe, a `heartbeat`-kind component
proves it ran by POSTing `/webhook/heartbeat`, which stamps `last_ok_at`
via `state.component_status.record_heartbeat`. This check just reads that
timestamp from the prior status row the sweep hands it: within
`component.max_staleness_s` of now → up; seen-then-overdue → down.

A never-seen heartbeat is `unknown`, NOT `down`: a component whose sender
isn't wired yet must not false-page. It goes `down` (and pages) only once it
has reported at least once and THEN falls silent past its window, a real
death (a backup/timer that ran before but stopped). `unknown` never counts
toward the down threshold and never pages; it surfaces in "everything alive?"
as "not yet reporting". Check-module grammar: one public
`check(component, prior_row)`.

FAILURE POLICY: pure timestamp compare, nothing to fail.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from apps.assistant.core.monitor.component import (
    DOWN,
    UNKNOWN,
    UP,
    CheckResult,
    Component,
)


def check(component: Component, prior_row: dict[str, Any] | None) -> CheckResult:
    last_ok_at = (prior_row or {}).get("last_ok_at")
    if not last_ok_at:
        return CheckResult(UNKNOWN, "no heartbeat received yet")

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=component.max_staleness_s)
    try:
        seen = datetime.fromisoformat(last_ok_at)
    except ValueError:
        return CheckResult(DOWN, f"unparseable last_ok_at {last_ok_at!r}")

    if seen >= cutoff:
        return CheckResult(UP, f"heartbeat {last_ok_at}")
    return CheckResult(DOWN, f"overdue since {last_ok_at}")
