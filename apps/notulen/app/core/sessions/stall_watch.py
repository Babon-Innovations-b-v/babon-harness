"""Daemon loop that pages when a live recording session goes quiet.

A healthy browser recording delivers a chunk every 5 seconds. When an
active ``recording`` session receives nothing for ``STALL_QUIET_SECS`` and
has not been finalized, the meeting is probably being lost right now (mic
permission revoked, phone died, browser killed) -- so someone gets paged
while there is still meeting left to save. One page per session
(``stall_paged_at`` dedup).

Owns: the staleness policy + the poll loop. Does NOT own the page copy
(``core/sessions/alert_recording.py``) or the 6-hour session retirement
(``core/sessions/stale_cleanup.py``).

FAILURE POLICY: Tier-2 loop -- each tick swallows + logs and retries on
the next tick; the per-job ``update_job`` inside a tick propagates into
that swallow (a failed dedup mark means at worst a repeat page, never a
missed one).
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from dashkit.core.db import get_db

from apps.notulen.app.core.sessions.alert_recording import (
    alert_recording_stalled,
)
from apps.notulen.app.shared.jobs_table import ensure_jobs_table
from apps.notulen.app.shared.update_job import update_job

logger = logging.getLogger("notulen")

# A chunk lands every 5s while recording; 90s of silence is ~18 missed
# chunks -- far past any network blip, early enough to save the meeting.
STALL_QUIET_SECS = 90
STALL_CHECK_INTERVAL_SECS = 30


def find_stalled_sessions(conn) -> list[tuple[str, str, float]]:
    """(job_id, title, quiet_secs) for unpaged recording sessions gone quiet.

    Quiet time counts from the last accepted chunk, or from session start
    when no chunk ever arrived (record pressed, nothing ever uploaded).
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, title, "
            "EXTRACT(EPOCH FROM (NOW() - COALESCE(last_chunk_at, created_at))) "
            "FROM notulen_jobs "
            "WHERE status = 'recording' AND stall_paged_at IS NULL "
            "AND COALESCE(last_chunk_at, created_at) < "
            f"NOW() - INTERVAL '{STALL_QUIET_SECS} seconds'"
        )
        return [(str(row[0]), row[1], float(row[2])) for row in cur.fetchall()]


def page_stalled_sessions(conn) -> None:
    """Page each stalled session once and mark it paged.

    Page before mark: the alert helper swallows notifier failures, so the
    only way to page twice is the mark itself failing -- a repeat page
    beats a missed one.
    """
    for job_id, title, quiet_secs in find_stalled_sessions(conn):
        logger.info(
            "recording session %s (%s) quiet for %.0fs -- paging",
            job_id, title, quiet_secs,
        )
        alert_recording_stalled(job_id, title, quiet_secs)
        update_job(job_id, stall_paged_at=datetime.now(timezone.utc))


def watch_stalled_recordings_loop() -> None:
    """Poll every STALL_CHECK_INTERVAL_SECS for quiet recording sessions."""
    while True:
        try:
            conn = get_db()
            if conn:
                try:
                    ensure_jobs_table(conn)
                    page_stalled_sessions(conn)
                finally:
                    conn.close()
        except Exception:
            # Tier-2 swallow (documented): the daemon must survive transient
            # DB outages; the next tick retries the same rows.
            logger.exception("stalled-recording watch loop error")
        time.sleep(STALL_CHECK_INTERVAL_SECS)
