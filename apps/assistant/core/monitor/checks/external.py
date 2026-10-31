"""`external` check: best-effort probe of a third-party API's health.

`component.target` is a cheap GET URL (Anthropic `/v1/models`,
GitHub `/rate_limit`). This is deliberately the
softest check kind: an external dependency hiccup is NOT a stack
outage, so a transport failure classifies `unknown`, never `down`, and
external components carry `page_on_down=False` in the registry as a
second belt. Only a clear unhealthy answer (5xx) from a reachable
endpoint counts as `down`.

For liveness, any HTTP answer proves the host is serving: an
auth-required (401/403) response on an unkeyed probe means the API is up
and rejecting us, so we classify it `up` ("reachable, auth-gated"). That
is what clears the Anthropic `/v1/models` 401 without putting a key in
the monitor, openclaw making real Anthropic calls already proves its
own key works. Check-module grammar: one public `check(component,
prior_row)`.

FAILURE POLICY: never raises for a transport/HTTP failure; worst case
returns `unknown`. The monitor cannot page on an external blip.
"""
from __future__ import annotations

import urllib.request
from typing import Any
from urllib.error import HTTPError, URLError

from apps.assistant.core.monitor.component import (
    DOWN,
    UNKNOWN,
    UP,
    CheckResult,
    Component,
)
from apps.assistant.core.monitor.limits import CHECK_TIMEOUT_SECONDS


def check(component: Component, prior_row: dict[str, Any] | None = None) -> CheckResult:
    request = urllib.request.Request(component.target, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=CHECK_TIMEOUT_SECONDS) as response:
            code = response.getcode()
    except HTTPError as exc:
        # The endpoint ANSWERED, for a liveness probe that alone proves the
        # third-party API is up. Auth-required (401/403) means "serving and
        # rejecting our unkeyed probe", i.e. alive → UP (this is what clears
        # the Anthropic /v1/models 401 without putting a key in the monitor;
        # openclaw making real Anthropic calls already proves its own key).
        # A 5xx is a genuine outage of the external API → down. Other 4xx
        # (e.g. 404 on a moved health URL) is ambiguous → unknown.
        if exc.code in (401, 403):
            return CheckResult(UP, f"reachable, auth-gated (HTTP {exc.code})")
        if 500 <= exc.code < 600:
            return CheckResult(DOWN, f"HTTP {exc.code}")
        return CheckResult(UNKNOWN, f"HTTP {exc.code}")
    except (URLError, TimeoutError) as exc:
        # Best-effort: an external unreachable is unknown, never down.
        return CheckResult(UNKNOWN, f"unreachable: {exc}")

    if 200 <= code < 400:
        return CheckResult(UP, f"HTTP {code}")
    return CheckResult(UNKNOWN, f"HTTP {code}")
