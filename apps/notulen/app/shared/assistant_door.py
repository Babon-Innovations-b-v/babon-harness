"""Post an operational message to the assistant's notify door.

Every page this dashboard raises (a recording that went quiet, a GPU job that
died, minutes stuck uncommitted) goes to one place: the assistant's
``/webhook/notify`` route, which decides when and how it reaches the owner's
phone. The dashboard never talks to Signal itself.

``OPENCLAW_NOTIFY_URL`` is the assistant's base URL and
``OPENCLAW_WEBHOOK_SECRET`` the bearer both sides share. Standard library
only, so the page path has no dependency that could be missing when it is
needed.

FAILURE POLICY: Tier-1 here, it raises on a missing setting or a non-2xx.
Every caller wraps it in its own documented Tier-2 swallow, because a broken
page path must never break a recording or the commit loop.
"""
from __future__ import annotations

import json
import os
import urllib.request

_TIMEOUT_S = 15


def notify_assistant(subject: str, body: str) -> None:
    """POST one message to ``{OPENCLAW_NOTIFY_URL}/webhook/notify``.

    Raises:
        KeyError: the door or its secret is not configured.
        urllib.error.URLError: the assistant did not take it.
    """
    base = os.environ.get("OPENCLAW_NOTIFY_URL", "").strip().rstrip("/")
    secret = os.environ.get("OPENCLAW_WEBHOOK_SECRET", "").strip()
    if not base:
        raise KeyError("OPENCLAW_NOTIFY_URL")
    if not secret:
        raise KeyError("OPENCLAW_WEBHOOK_SECRET")
    payload = json.dumps({"subject": subject, "body": body, "source": "notulen"}).encode()
    request = urllib.request.Request(
        f"{base}/webhook/notify",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {secret}"},
    )
    with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
        response.read()
