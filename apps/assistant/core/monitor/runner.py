"""Background sweep runner, the daemon thread that drives `run_sweep`
on an interval Inside the assistant container.

NOT a CronJob: openclaw's SQLite lives on a named volume only this pod can
mount, so the sweep must run in-process. `start_runner()` spawns ONE
daemon thread (guarded by a module flag + lock so a double FastAPI
startup can't start two) that loops `run_sweep()` then sleeps
`SWEEP_INTERVAL_SECONDS`. The thread is a plain (non-async) daemon, so
its blocking checks (HTTP GET, DB connect, kubectl) run OFF the event
loop, `/health` stays responsive while a sweep is mid-flight.

FAILURE POLICY: Tier-2, the loop body is wrapped so a sweep that raises
(it shouldn't; `run_sweep` guards each component) is logged and the loop
continues. A daemon thread dying would silently stop monitoring, so the
loop must never let an exception escape. Pod-down itself is covered by
the independent deadman switch, not this thread.
"""
from __future__ import annotations

import logging
import threading

from apps.assistant.core.monitor import dead_letters, unrecorded_roads
from apps.assistant.core.monitor.limits import SWEEP_INTERVAL_SECONDS
from apps.assistant.core.monitor.sweep import run_sweep

log = logging.getLogger("openclaw.monitor.runner")

_start_lock = threading.Lock()
_thread: threading.Thread | None = None
_stop = threading.Event()


def start_runner() -> None:
    """Start the sweep loop once. Idempotent: a second call while the
    thread is alive is a no-op (guards a double FastAPI startup)."""
    global _thread
    with _start_lock:
        if _thread is not None and _thread.is_alive():
            return
        _stop.clear()
        _thread = threading.Thread(
            target=_loop, name="openclaw-stack-sweep", daemon=True
        )
        _thread.start()
        log.info("stack-liveness sweep runner started (interval %ds)", SWEEP_INTERVAL_SECONDS)


def stop_runner() -> None:
    """Signal the loop to stop after its current sleep (test hook / clean
    shutdown). The daemon thread also dies with the process regardless."""
    _stop.set()


def _loop() -> None:
    """Run a sweep, then wait the interval, until stopped. A raising
    sweep is logged and the loop continues (Tier-2, monitoring must not
    die on one bad pass)."""
    while not _stop.is_set():
        try:
            transitions = run_sweep()
            if transitions:
                log.info("sweep produced %d transition(s)", len(transitions))
        except Exception as exc:  # noqa: BLE001, Tier-2: keep the loop alive
            log.error("sweep raised (swallowed): %s", exc)
        try:
            # Separate from the sweep on purpose: the sweep
            # IS the paging path, this is a check on it, so a bug here cannot
            # take monitoring down with it.
            found = dead_letters.check()
            held = dead_letters.stranded()
            if held:
                # The third state: the watch found something and no channel
                # took the report. It is not "nothing to report" and it is not a
                # report, so it is not logged as either.
                log.error(
                    "%d dead-lettered page(s) reached nobody; held for the next pass",
                    held,
                )
            elif found:
                log.warning("%d page(s) were decided and never delivered", found)
        except Exception as exc:  # noqa: BLE001, Tier-2: keep the loop alive
            log.error("dead-letter check raised (swallowed): %s", exc)
        try:
            # Its own try block for the same reason as the one above: a check ON
            # the paging path must not be able to stop the path.
            roads_in_gap = unrecorded_roads.check()
            unreported = unrecorded_roads.stranded()
            if unreported:
                log.error(
                    "%d road(s) that stopped recording reached nobody; held",
                    unreported,
                )
            elif roads_in_gap:
                log.warning(
                    "%d road(s) delivered messages and recorded none of them",
                    roads_in_gap,
                )
        except Exception as exc:  # noqa: BLE001, Tier-2: keep the loop alive
            log.error("unrecorded-road check raised (swallowed): %s", exc)
        # Interruptible sleep: stop_runner() wakes it immediately.
        _stop.wait(SWEEP_INTERVAL_SECONDS)
