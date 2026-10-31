"""`http` check: GET the component's target URL; 2xx/3xx = up.

Stdlib urllib only (mirrors `shared/notify.py`), short
timeout from `monitor.limits`. A connection error / timeout / 4xx / 5xx
is `down` (the surface is reachable-and-broken or unreachable, both of
which the owner wants paged). Check-module grammar: one public `check`.

FAILURE POLICY: this module never raises for a transport failure, it
returns a `down` CheckResult with the error in detail. An unexpected
bug still propagates to the sweep's own per-component catch (Tier-2),
which classifies it down without crashing the sweep.
"""
from __future__ import annotations

import urllib.request
from typing import Any
from urllib.error import HTTPError, URLError

from apps.assistant.core.monitor.component import (
    DOWN,
    UP,
    CheckResult,
    Component,
)
from apps.assistant.core.monitor.limits import CHECK_TIMEOUT_SECONDS


def check(component: Component, prior_row: dict[str, Any] | None = None) -> CheckResult:
    # Active probe, `prior_row` is unused (heartbeat is the only check
    # that reads prior state); the uniform signature lets the registry
    # dispatch every kind the same way.
    request = urllib.request.Request(component.target, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=CHECK_TIMEOUT_SECONDS) as response:
            code = response.getcode()
    except HTTPError as exc:
        # An HTTP error response (4xx/5xx) reached us, the surface
        # answered, unhealthily. Treat 3xx-redirect codes that urllib
        # surfaces as errors as up (it usually follows them, but be
        # defensive).
        if 300 <= exc.code < 400:
            return CheckResult(UP, f"HTTP {exc.code}")
        return CheckResult(DOWN, f"HTTP {exc.code}")
    except (URLError, TimeoutError) as exc:
        return CheckResult(DOWN, f"unreachable: {exc}")

    if 200 <= code < 400:
        return CheckResult(UP, f"HTTP {code}")
    return CheckResult(DOWN, f"HTTP {code}")
