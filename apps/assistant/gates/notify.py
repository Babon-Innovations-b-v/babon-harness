"""Notify webhook -> Notification adapter.

The openclaw notify gateway (`/webhook/notify`) is the funnel the
VM-side + serverless notify seams pass through so every page leaves
the project FROM the dedicated bot number with an audit row. Senders POST a
flat `{"subject", "body", "source"}` body, optionally with a `facts`
object; this gate turns it into a `Notification`. No triage here:
alerts that need LLM triage hit `/webhook/alertmanager`; this is a
pass-through send.

`facts` is the sender saying, in fields rather than in prose, what it
knows about its own ping. It is optional at every step: a sender
that marks nothing sends what it always sent, and the reading of the
body underneath is unchanged.

WHY THE FIELD NAMES ARE NOT CHECKED HERE. This gate checks the SHAPE of
`facts` and nothing else, because `core.ping_facts` is the module whose
whole contract is that everything downstream may only say what a typed
field carries, and a second copy of the vocabulary here is a second copy
to drift. What lands in the pen is what the sender wrote; what anything
is allowed to SAY is what `ping_facts` could type out of it. A key
nobody reads is dropped there, silently and by design, and the gate's
own log line names the keys that arrived so a sender's typo is visible
next to the ping it came with.

Single public callable: `parse(payload)`; `Notification` is its
signature type and rides with it.

FAILURE POLICY: fail-loud on the ping, degrade on the marking. A
malformed `subject`, `body` or `source` raises `ValueError`, which the
FastAPI gate maps to a 400; there are no partial parses of those three.
A `facts` value that is not an object is dropped and the ping still
lands. That asymmetry is the point of the field: a 400 here costs the
whole page, because the caller's gateway retry runs out and the phone
gets a pointer to Talk instead of the alert, and paying that for a
mistyped enrichment is exactly the "breaks" this key exists to avoid.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Notification:
    subject: str
    body: str
    source: str
    facts: dict[str, Any] | None = None


def _marking(value: Any) -> dict[str, Any] | None:
    """The sender's `facts` object, or None when it marked nothing readable.

    An absent key, a null, an empty object and a value that is not an object
    at all are one answer here: this sender marked nothing. Only the shape is
    judged; see the module docstring for why the field names are not.
    """
    if not isinstance(value, dict) or not value:
        return None
    return dict(value)


def parse(payload: dict[str, Any]) -> Notification:
    if not isinstance(payload, dict):
        raise ValueError("notify payload: body must be an object")
    subject = payload.get("subject")
    body = payload.get("body")
    source = payload.get("source", "notify")
    if not isinstance(subject, str) or not subject.strip():
        raise ValueError("notify payload: 'subject' must be a non-empty string")
    if not isinstance(body, str):
        raise ValueError("notify payload: 'body' must be a string")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("notify payload: 'source' must be a non-empty string")
    return Notification(
        subject=subject,
        body=body,
        source=source,
        facts=_marking(payload.get("facts")),
    )
