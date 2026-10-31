"""`post_heartbeat(component, secret)`: beat one stack component by name.

A caller that proves one specific thing alive (the Signal send canary beats
`signal-send` only when a real message was accepted) posts it here rather than
keeping its own copy of the URL and bearer handling. The door marks the
component up; a component that stops beating is flipped down by the sweep once
its window in `core/monitor/registry.py` lapses.

FAILURE POLICY: never raises. A failed post is logged and answered False, so
the caller decides whether that is worth a page.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from urllib.error import HTTPError, URLError

from apps.assistant.watch.door import door_url

log = logging.getLogger("openclaw.watch.heartbeat")

_ROUTE = "/webhook/heartbeat"
_POST_TIMEOUT_S = 10


def post_heartbeat(component: str, secret: str) -> bool:
    """POST one heartbeat. True on a 2xx, False on any failure."""
    body = json.dumps({"component": component}).encode()
    request = urllib.request.Request(
        door_url() + _ROUTE, data=body, method="POST",
        headers={"Authorization": f"Bearer {secret}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=_POST_TIMEOUT_S) as response:
            return 200 <= response.getcode() < 300
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        log.warning("heartbeat post for %s failed: %s", component, exc)
        return False
