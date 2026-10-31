"""The relay's two calls to the assistant: hand over alerts, and check the door.

Both go to ASSISTANT_URL (compose sets `http://assistant:${OPENCLAW_PORT}`)
with the bearer OPENCLAW_WEBHOOK_SECRET, the same one the assistant's
`/webhook/alertmanager` gate checks.

FAILURE POLICY: `forward_alerts` raises on anything but a 2xx, so the relay
answers Alertmanager with a 500 and Alertmanager retries; an alert is never
dropped on a refused delivery. `check_assistant` never raises: what it finds is
the answer.
"""
from __future__ import annotations

import json
import os
import urllib.request
from urllib.error import HTTPError, URLError

_EMPTY_ENVELOPE = {"version": "4", "alerts": []}


def _base_url() -> str:
    explicit = os.environ.get("ASSISTANT_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    return f"http://assistant:{os.environ.get('OPENCLAW_PORT', '').strip() or '8000'}"


def _post(payload: dict, timeout: float) -> int:
    request = urllib.request.Request(
        f"{_base_url()}/webhook/alertmanager",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.environ.get('OPENCLAW_WEBHOOK_SECRET', '').strip()}",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        response.read()
        return int(response.status)


def forward_alerts(payload: dict) -> None:
    """POST the Alertmanager payload to the assistant. Raises unless it took it."""
    _post(payload, timeout=60)


def check_assistant() -> dict:
    """Is the assistant alive, and does it accept this relay's bearer?

    POSTs an envelope with no alerts in it: the gate authenticates, parses and
    triages nothing, so the real delivery path is exercised without paging.
    Only 401 and 403 count as refusal; any other answer is left to `/health`.
    """
    answer = {"alive": False, "accepts": False, "detail": ""}
    try:
        with urllib.request.urlopen(f"{_base_url()}/health", timeout=8) as response:
            answer["alive"] = 200 <= response.status < 300
    except (HTTPError, URLError, OSError) as exc:
        answer["detail"] = str(exc)
        return answer
    try:
        _post(_EMPTY_ENVELOPE, timeout=8)
        answer["accepts"] = True
    except HTTPError as exc:
        answer["accepts"] = exc.code not in (401, 403)
        answer["detail"] = f"HTTP {exc.code} on /webhook/alertmanager"
    except (URLError, OSError) as exc:
        answer["accepts"] = True
        answer["detail"] = f"delivery check inconclusive: {exc}"
    return answer
