"""Check-kind registry, the seam that maps a `Component.kind` to its
check callable.

One module per check kind, each exposing a single
`check(component, prior_row) -> CheckResult`:

    http.py           GET a URL; 2xx/3xx = up
    db.py             connect + SELECT 1 on a read-only DSN
    kubectl.py        a Deployment has >=1 ready replica
    heartbeat.py      push-only: last_ok_at within max-staleness
    external.py       best-effort third-party API probe (never pages)

`run_check(component, prior_row)` dispatches by kind. The sweep is the
only caller; it wraps this in its own Tier-2 catch so a check that
raises becomes a `down`/`unknown` row instead of crashing the sweep.

FAILURE POLICY: the dispatcher itself is pure (a dict lookup); an
unknown kind returns an `unknown` CheckResult rather than raising, so a
registry typo degrades softly. Each check module owns its own
transport-failure handling (see their docstrings).
"""
from __future__ import annotations

from typing import Any, Callable

from apps.assistant.core.monitor.checks import (
    db as _db,
    external as _external,
    heartbeat as _heartbeat,
    http as _http,
    kubectl as _kubectl,
)
from apps.assistant.core.monitor.component import (
    KIND_DB,
    KIND_EXTERNAL,
    KIND_HEARTBEAT,
    KIND_HTTP,
    KIND_KUBECTL,
    UNKNOWN,
    CheckResult,
    Component,
)

Check = Callable[[Component, "dict[str, Any] | None"], CheckResult]

_CHECK_FOR_KIND: dict[str, Check] = {
    KIND_HTTP: _http.check,
    KIND_DB: _db.check,
    KIND_KUBECTL: _kubectl.check,
    KIND_HEARTBEAT: _heartbeat.check,
    KIND_EXTERNAL: _external.check,
}


def run_check(component: Component, prior_row: dict[str, Any] | None) -> CheckResult:
    """Dispatch `component` to its kind's check callable."""
    check = _CHECK_FOR_KIND.get(component.kind)
    if check is None:
        return CheckResult(UNKNOWN, f"no check for kind {component.kind!r}")
    return check(component, prior_row)


__all__ = ["Check", "run_check"]
