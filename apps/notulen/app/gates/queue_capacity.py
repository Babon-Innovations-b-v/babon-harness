"""Concurrent-job queue gate for POST /api/upload/start.

FAILURE POLICY: raises ``HTTPException`` 429 with user copy when the
server is at its concurrent-job cap (memory ceiling); DB errors propagate
(Tier-1: an unreachable DB must 5xx, not admit unlimited jobs).
"""
from __future__ import annotations

from fastapi import HTTPException

from apps.notulen.app.shared.jobs_table import ensure_jobs_table

MAX_QUEUED_JOBS = 2  # server memory ceiling: one transcription + one in queue

# Statuses that occupy a queue slot. ``recording`` holds the slot from /start
# until /finalize or /abort, so a half-finished session can't be displaced.
QUEUE_OCCUPYING_STATUSES = ("recording", "pending", "transcribing", "structuring")


def check_queue_capacity(conn) -> None:
    """Reject if the server is already at its concurrent-job cap. Caller owns ``conn``."""
    ensure_jobs_table(conn)
    placeholders = ", ".join(["%s"] * len(QUEUE_OCCUPYING_STATUSES))
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM notulen_jobs WHERE status IN ({placeholders})",
            QUEUE_OCCUPYING_STATUSES,
        )
        queued = cur.fetchone()[0]
        if queued >= MAX_QUEUED_JOBS:
            raise HTTPException(
                status_code=429,
                detail="Recordings are already being processed, please try again later",
            )
