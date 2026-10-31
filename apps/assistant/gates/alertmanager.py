"""Alertmanager v4 webhook -> Alert[] adapter.

AM POSTs a single envelope with N alerts. We split it into N alerts, and
`core.triage.triage_envelope` makes one triage call per cause.

AM payload shape (`https://prometheus.io/docs/alerting/latest/configuration/#webhook_config`):

    {
      "version": "4",
      "groupKey": "...",
      "status": "firing|resolved",
      "alerts": [
        {"status": "firing", "labels": {...}, "annotations": {...},
         "startsAt": "...", "endsAt": "...", "fingerprint": "..."},
        ...
      ]
    }

Single public callable: `parse(payload)`.

FAILURE POLICY: fail-loud, malformed input raises `ValueError`, which
the FastAPI gate maps to a 400 (Alertmanager logs the rejection). No
partial parses: one bad alert in the envelope rejects the whole POST.
"""
from __future__ import annotations

from typing import Any

from apps.assistant.core.triage import Alert


def parse(payload: dict[str, Any]) -> list[Alert]:
    # The body has to be an OBJECT before anything asks it for a key. Without
    # this line `null`, a list, a bare string, `7` and `true` are all valid
    # JSON that reach `.get` and raise AttributeError, which is not a
    # ValueError, so it escapes the gate's handler and answers 500 instead of
    # 400. The three sibling adapters (notify.py:30, signal.py:38,
    # heartbeat.py:29) open the same way, and the malformed-input tests post
    # non-objects to all four.
    #
    # A 500 matters more than it looks: Alertmanager RETRIES a 5xx, so a body
    # it will never send differently would be resent on a loop, and the one
    # shape that should be rejected once instead becomes traffic.
    if not isinstance(payload, dict):
        raise ValueError("AM payload: body must be an object")
    raw_alerts = payload.get("alerts", [])
    if not isinstance(raw_alerts, list):
        raise ValueError("AM payload: 'alerts' must be a list")

    parsed: list[Alert] = []
    for raw in raw_alerts:
        if not isinstance(raw, dict):
            raise ValueError("AM payload: each alert must be an object")
        status = raw.get("status", "firing")
        if status not in ("firing", "resolved"):
            raise ValueError(f"AM payload: unexpected status {status!r}")
        parsed.append(
            Alert(
                fingerprint=str(raw.get("fingerprint", "")),
                status=status,
                labels=dict(raw.get("labels") or {}),
                annotations=dict(raw.get("annotations") or {}),
                starts_at=str(raw.get("startsAt", "")),
                ends_at=str(raw.get("endsAt", "")),
                source="alertmanager",
            )
        )
    return parsed
