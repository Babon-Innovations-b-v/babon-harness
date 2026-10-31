"""Outbound Signal dispatch with retry + dead-letter.

Delegates the actual HTTPS call to `apps.assistant.shared.notify.send_signal`
so we don't carry a parallel signal-cli implementation. This module owns
only the policy: retry-once-after-5s, dead-letter on second failure, and
the last rewrite before a person reads the text: a time marked UTC goes out
on the local clock (`local_time`), except on a machine page,
the one kind that carries a subject.

Inside the assistant container OPENCLAW_GATEWAY_SELF=1, so `notify.send_signal`
sends signal-cli direct (it does not re-POST to its own notify gateway).
This is the container's own send path the /webhook/notify gateway reuses.

FAILURE POLICY: Tier-2 best-effort with dead-letter, the package's one
sanctioned swallow. `send()` never raises, a Signal outage must not
abort the triage loop mid-webhook. Failure surfaces three ways: the
returned `False`, the structured dead-letter log line, and the
`dead_letter=1` audit row the gate writes. Never a silent drop.
"""
from __future__ import annotations

import logging
import time

from apps.assistant.shared.notify import send_signal as _send_signal_raw
from apps.assistant.shared.local_time import in_local_time

log = logging.getLogger("openclaw.signal")

_RETRY_DELAY_SECONDS = 5.0


def send(subject: str, body: str, *, recipient: str | None = None) -> bool:
    """Try signal-cli once. On failure, sleep 5s and retry. On second
    failure, log a structured dead-letter line and return False.

    Failures propagate as `False`, callers should record the result
    against the alert row (slice 4 SQLite). Never raise: the triage
    loop must finish even if Signal is unreachable.

    `recipient` (an E.164 number) overrides the pinned ops destination so
    A teammate message reaches that teammate; default None keeps
    the ops recipient.
    """
    body = _for_the_reader(subject, body)
    if _send_signal_raw(subject, body, recipient=recipient):
        return True
    log.warning(
        "signal first attempt failed for %r; retrying in %.1fs",
        subject,
        _RETRY_DELAY_SECONDS,
    )
    time.sleep(_RETRY_DELAY_SECONDS)
    if _send_signal_raw(subject, body, recipient=recipient):
        return True
    log.error(
        "signal dead-letter: subject=%r body_len=%d",
        subject,
        len(body),
    )
    return False


def _for_the_reader(subject: str, body: str) -> str:
    """The body with its UTC times on the local clock (`local_time`), except
    under a subject: a subject marks a machine page (`notify` prints it as the
    banner line), and that one goes out as the sender wrote it."""
    if subject:
        return body
    return in_local_time(body)
