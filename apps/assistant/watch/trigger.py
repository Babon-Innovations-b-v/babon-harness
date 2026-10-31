"""Fire one of the door's scheduled passes.

The passes run IN the door behind bearer-gated webhook routes; this
server-side trigger just POSTs the given path once (the patrol, meeting
reminder and weekly compact timers). It carries no payload; the work is all
in the door. One trigger implementation for every timer; the unit's exec
argument picks the pass. The weekday brief and the weekly advisor are not
here: the gateway runs them as its own automations
(`workspace/gateway_automations.json`).

Single public callable: `trigger(path)`.

FAILURE POLICY: fail-loud, no exception swallowed. A missing secret, an
unknown path or a non-2xx response raises so the systemd `OnFailure=` fires:
if a scheduled pass cannot be fired we want a record of it, not a silently
missed pass. Muting the PHONE during a known outage belongs to the failure
notifier one level out, which can tell "do not page" from "do not record";
this module cannot, so it always fails loud.
"""
from __future__ import annotations

from apps.assistant.watch.door import door_url

import logging
import os
import socket
import time
import urllib.request
from urllib.error import HTTPError, URLError

log = logging.getLogger("openclaw.trigger")

_BASE_URL = door_url()
# The routes the timers may fire: fail loud on a mistyped unit argument
# rather than POSTing an arbitrary path.
KNOWN_PATHS = ("/webhook/compact", "/webhook/patrol", "/webhook/meeting-reminders")
_SECRET_ENV = "OPENCLAW_WEBHOOK_SECRET"
# The door runs a full model pass before it answers, so this is a wait, not a
# health check: a slow model call or a tool that hangs its budget runs long.
_TIMEOUT_S = 300

# The door can be briefly unreachable while a deploy recreates it. A scheduled
# job must not fail and page on that blip, so a refused connection or a 502 is
# retried across the restart window. A bad bearer (401/403) and other 4xx are
# config errors: fail fast, never retry.
_MAX_ATTEMPTS = 4
_RETRY_BACKOFF_S = 40
_RETRYABLE_STATUS = (502, 503, 504)


def trigger(path: str) -> None:
    """POST the given webhook path so the container runs that pass, retrying
    across a transient tunnel-forward blip. A pass that cannot be fired
    raises, so the miss is always recorded."""
    if path not in KNOWN_PATHS:
        raise RuntimeError(
            f"unknown openclaw trigger path {path!r}; known: {', '.join(KNOWN_PATHS)}"
        )
    secret = os.environ.get(_SECRET_ENV, "")
    if not secret:
        raise RuntimeError(f"{_SECRET_ENV} unset, cannot trigger {path}")
    request = urllib.request.Request(
        f"{_BASE_URL}{path}",
        data=b"",
        method="POST",
        headers={"Authorization": f"Bearer {secret}"},
    )
    last_error = ""
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
                code = response.getcode()
                body = response.read().decode()[:200]
            log.info("%s triggered: HTTP %d %s", path, code, body)
            return
        except HTTPError as exc:
            if exc.code not in _RETRYABLE_STATUS:
                # 401/other 4xx are config errors, retrying won't help.
                raise RuntimeError(
                    f"{path} trigger got HTTP {exc.code}: {exc}"
                ) from exc
            last_error = f"HTTP {exc.code}"
        except (TimeoutError, socket.timeout) as exc:
            # The container TOOK the request and is still working on it. Retrying
            # POSTs the same route again while the first pass is running and
            # about to send, and no beat route is idempotent: one timer firing
            # could put two different notes on a phone, and the unit would
            # still report Result=success.
            #
            # The retry ladder exists for a zombie tunnel-forward right after a
            # container restart, which fails at CONNECT with a refused connection or a
            # 502. A read timeout is the opposite situation: the trigger did its
            # job, so it stops here and says so rather than firing again.
            log.warning(
                "%s accepted but still running after %ds; not retrying, a "
                "second POST would run the pass twice and send twice: %s",
                path, _TIMEOUT_S, exc,
            )
            return
        except (URLError, OSError) as exc:
            reason = getattr(exc, "reason", None)
            if isinstance(reason, (TimeoutError, socket.timeout)):
                log.warning(
                    "%s accepted but still running after %ds; not retrying: %s",
                    path, _TIMEOUT_S, exc,
                )
                return
            last_error = str(exc)
        if attempt < _MAX_ATTEMPTS:
            log.warning(
                "%s trigger attempt %d/%d failed (%s); retrying in %ds",
                path, attempt, _MAX_ATTEMPTS, last_error, _RETRY_BACKOFF_S,
            )
            time.sleep(_RETRY_BACKOFF_S)
    raise RuntimeError(
        f"{path} trigger POST failed after {_MAX_ATTEMPTS} attempts: {last_error}"
    )
