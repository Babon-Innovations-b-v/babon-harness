"""Notulen dashboard app assembly.

Records audio in the browser via the MediaRecorder API, transcribes it on the
GPU worker (or on this container's CPU when the GPU tier is off), and writes
structured meeting minutes with the Claude API from the minutes template.

This file is the thin bootstrap only: build the ``DashkitConfig``, call
``make_dashboard_app``, attach the route modules, register the startup hooks.
Routes live beside it in ``entrypoints/``; domain logic lives in ``core/``.

FAILURE POLICY: startup hooks run threads that own their own policies (see
``core/publish/retry/git_writer_loop.py``, ``core/sessions/``); app assembly
itself fails loud, because a bad config must kill the container.
"""
from __future__ import annotations

import logging
import sys
import threading

from dashkit.core.app_factory import (
    DashkitConfig,
    make_dashboard_app,
)

from apps.notulen.app.core.publish.retry.git_writer_loop import git_writer_loop
from apps.notulen.app.core.sessions.dead_gpu_jobs import (
    watch_dead_gpu_jobs_loop,
)
from apps.notulen.app.core.sessions.recovery import (
    recover_interrupted_jobs,
)
from apps.notulen.app.core.sessions.stale_cleanup import (
    cleanup_stale_recordings_loop,
)
from apps.notulen.app.core.sessions.stall_watch import (
    watch_stalled_recordings_loop,
)
from apps.notulen.app.entrypoints.health_routes import (
    router as health_router,
)
from apps.notulen.app.entrypoints.jobs_routes import (
    router as jobs_router,
)
from apps.notulen.app.entrypoints.minutes_routes import (
    router as minutes_router,
)
from apps.notulen.app.entrypoints.people_routes import (
    router as people_router,
)
from apps.notulen.app.entrypoints.spa_routes import (
    router as spa_router,
)
from apps.notulen.app.entrypoints.talk_routes import (
    router as talk_router,
)
from apps.notulen.app.entrypoints.upload_routes import (
    router as upload_router,
)


def _wire_notulen_logging() -> None:
    """Send the ``notulen`` logger to container stdout at INFO.

    Without this the logger sits at the root's WARNING with no handler, so
    every ``log.info`` on the recording path is dropped. Idempotent: only adds
    a handler once (module import and tests can re-run).
    """
    notulen_logger = logging.getLogger("notulen")
    notulen_logger.setLevel(logging.INFO)
    if not any(isinstance(h, logging.StreamHandler) for h in notulen_logger.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s notulen: %(message)s")
        )
        notulen_logger.addHandler(handler)
    notulen_logger.propagate = False


_wire_notulen_logging()

config = DashkitConfig(
    domain="notulen",
    title="Minutes",
    activity_table="notulen_activity",
    ai_calls_table="notulen_ai_calls",
    health_checks=[],
)
app = make_dashboard_app(config)

app.include_router(spa_router)
app.include_router(upload_router)
app.include_router(jobs_router)
app.include_router(minutes_router)
app.include_router(health_router)
app.include_router(people_router)
app.include_router(talk_router)


@app.on_event("startup")
def _start_git_writer():
    """Start the background git writer thread (commit catch-up)."""
    threading.Thread(target=git_writer_loop, daemon=True).start()


@app.on_event("startup")
def _start_stale_recording_cleanup():
    """Hourly auto-abort of forgotten recording sessions older than 6h."""
    threading.Thread(target=cleanup_stale_recordings_loop, daemon=True).start()


@app.on_event("startup")
def _start_stalled_recording_watch():
    """Page when a live recording session stops sending chunks."""
    threading.Thread(target=watch_stalled_recordings_loop, daemon=True).start()


@app.on_event("startup")
def _start_dead_gpu_job_watch():
    """Fail the row of a GPU job Kubernetes gave up on."""
    threading.Thread(target=watch_dead_gpu_jobs_loop, daemon=True).start()


@app.on_event("startup")
def _recover_interrupted_jobs():
    """Reset jobs stuck in processing state (server crashed mid-job).

    GPU-path jobs are only failed when their Kubernetes Job is gone; see
    ``core/sessions/recovery.py``.
    """
    recover_interrupted_jobs()
