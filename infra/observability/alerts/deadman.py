"""The shared clockwork of the two deadmen: count failures, page a state change once.

`assistant_deadman` and `gateway_deadman` each run every 60 seconds as a systemd
oneshot, probe one thing, and hand the result here. Three consecutive failures
(about three minutes) count as down: a single miss is a restart or a deploy,
and paging on one turns the watcher into the noise source.

Public callables: `decide()` is the pure verdict, `run_cycle()` persists the
count and pages. They are split so the threshold and the page-once behaviour
can be tested without a server or a phone.

FAILURE POLICY: what the probe observes is data, never an exception. A page is
sent with `signal_direct=True`, never through the assistant, because a canary
must not report through the thing it watches. The cooldown cursor is stamped
only for a page a road took, so a page that reached nobody is retried on the
next tick. State reads that fail fall back to 0, which pages late rather than
never.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

log = logging.getLogger("harness.deadman")

#: Consecutive failures before the watched thing counts as down.
FAIL_THRESHOLD = 3
#: Floor between two pages of the same kind, so a long outage reminds hourly.
PAGE_COOLDOWN_S = 3600


def state_dir() -> Path:
    """Where flags, counters and cursors live (HARNESS_STATE_DIR)."""
    return Path(os.environ.get("HARNESS_STATE_DIR", "/var/lib/harness"))


@dataclass(frozen=True)
class Verdict:
    """What one cycle decided, before any side effect."""

    failures: int
    down: bool
    #: "down" on the cycle it goes down, "up" on the cycle it comes back, else "".
    page: str


def decide(*, healthy: bool, failures_before: int) -> Verdict:
    """Turn one probe result and the previous count into this cycle's verdict."""
    if healthy:
        was_down = failures_before >= FAIL_THRESHOLD
        return Verdict(failures=0, down=False, page="up" if was_down else "")
    failures = failures_before + 1
    return Verdict(
        failures=failures,
        down=failures >= FAIL_THRESHOLD,
        page="down" if failures == FAIL_THRESHOLD else "",
    )


def _read_int(path: Path) -> int:
    try:
        return int(path.read_text().strip() or "0")
    except (ValueError, OSError):
        return 0


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)


def _page(
    name: str,
    state_change: str,
    message: tuple[str, str],
    send: Callable[..., dict[str, bool]],
    now: float,
) -> bool:
    """Send one page about a state change. True when somebody has it.

    True also covers the cooldown: a page of this kind landed less than an hour
    ago, so holding this one is intended. Separate cursors for down and up.
    """
    cursor = state_dir() / f"{name}-cursor-{state_change}"
    if now - _read_int(cursor) < PAGE_COOLDOWN_S:
        return True
    subject, body = message
    if not any(send(subject, body, signal_direct=True).values()):
        return False
    _write(cursor, str(int(now)))
    return True


def run_cycle(
    name: str,
    *,
    healthy: bool,
    down_message: tuple[str, str],
    up_message: tuple[str, str],
    send: Callable[..., dict[str, bool]],
    now: float | None = None,
) -> Verdict:
    """Persist one probe result under `name` and page a state change.

    While down, every cycle offers the page and the cursor rate-limits it, so a
    page that reached no road is retried a minute later. Returns the verdict;
    the caller decides what else follows (the assistant deadman's flag).
    """
    moment = time.time() if now is None else now
    counter = state_dir() / f"{name}-fails"
    verdict = decide(healthy=healthy, failures_before=_read_int(counter))
    _write(counter, str(verdict.failures))
    announcement = verdict.page or ("down" if verdict.down else "")
    if announcement:
        message = down_message if announcement == "down" else up_message
        if not _page(name, announcement, message, send, moment):
            log.error("%s is %s and the page reached nobody; retrying next tick", name, announcement)
    return verdict
