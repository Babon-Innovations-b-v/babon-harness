"""Heartbeat webhook -> Heartbeat adapter.

Push-only liveness for `heartbeat`-kind registry components: scheduled
jobs / backups / VM timers that openclaw can't actively reach POST
`{"component": ...}` to `/webhook/heartbeat` to prove they ran. This gate
turns that body into a `Heartbeat`, raising `ValueError` on malformed
input, the same shape-in-only contract as the alertmanager/signal/notify
gates (no decision logic here; the record write lives in
`state.component_status.record_heartbeat`).

Single public callable: `parse(payload)`; `Heartbeat` is its signature
type and rides with it.

FAILURE POLICY: fail-loud, malformed input raises `ValueError`, which
the FastAPI gate maps to a 400. No partial parses.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Heartbeat:
    component: str


def parse(payload: dict[str, Any]) -> Heartbeat:
    if not isinstance(payload, dict):
        raise ValueError("heartbeat payload: body must be an object")
    component = payload.get("component")
    if not isinstance(component, str) or not component.strip():
        raise ValueError("heartbeat payload: 'component' must be a non-empty string")
    return Heartbeat(component=component.strip())
