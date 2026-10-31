"""assistant_is_down: read the deadman flag the assistant deadman writes.

The flag is `$HARNESS_STATE_DIR/assistant-down` on the host (override with
ASSISTANT_DOWN_FLAG_PATH), mounted read-only into the relay container. The
deadman rewrites it every 60 s while the assistant is down, so a flag older
than 300 s means the deadman stopped writing, not that the assistant is down.

FAILURE POLICY: a pure read that fails toward "up". Answering "down" on a stale
or unreadable flag would send every alert raw to the phone for ever. Because
"the deadman looked and all is fine" and "this container cannot see the flag
directory at all" would otherwise give the same answer, a missing directory is
logged, and `flag_mount_present` reports it to `/assistant-check`.
"""
from __future__ import annotations

import logging
import os
import time

FLAG_MAX_AGE_S = 300

log = logging.getLogger("alert_relay.assistant_gate")
_last_warned = {"at": 0.0}


def flag_path() -> str:
    explicit = os.environ.get("ASSISTANT_DOWN_FLAG_PATH", "").strip()
    if explicit:
        return explicit
    return os.path.join(os.environ.get("HARNESS_STATE_DIR", "/var/lib/harness"), "assistant-down")


def flag_mount_present(path: str | None = None) -> bool:
    """Whether this process can see the flag's directory at all."""
    return os.path.isdir(os.path.dirname(path or flag_path()) or ".")


def assistant_is_down(*, now: float | None = None, path: str | None = None) -> bool:
    """True while the flag exists and is at most FLAG_MAX_AGE_S old."""
    moment = time.time() if now is None else now
    path = path or flag_path()
    if not flag_mount_present(path):
        if moment - _last_warned["at"] >= FLAG_MAX_AGE_S:
            _last_warned["at"] = moment
            log.error(
                "deadman flag directory %s is not mounted here: the raw safety net "
                "cannot engage. Mount the state directory read-only into alert-relay.",
                os.path.dirname(path),
            )
        return False
    try:
        flag_mtime = os.path.getmtime(path)
    except OSError:
        return False
    return (moment - flag_mtime) <= FLAG_MAX_AGE_S
