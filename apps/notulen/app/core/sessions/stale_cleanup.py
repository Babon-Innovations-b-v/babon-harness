"""Daemon loop that retires forgotten ``recording`` sessions.

Owns the staleness policy (6 h covers any plausible real meeting); what
retiring one session means, including keeping its audio, lives in
``core/sessions/retire_session.py``. Does NOT own startup crash recovery
(``core/sessions/recovery.py``): that deliberately leaves ``recording``
rows alone so a re-opened tab can resume from IndexedDB; this loop is what
finally retires them.

FAILURE POLICY: Tier-2 loop: each tick swallows + logs and retries on the
next tick (a transient DB blip must not kill the daemon thread); the
per-job ``update_job`` inside a tick propagates into that swallow.
"""
from __future__ import annotations

import logging
import time

from dashkit.core.db import get_db

from apps.notulen.app.core.sessions.retire_session import (
    retire_stale_session,
)
from apps.notulen.app.shared.jobs_table import ensure_jobs_table

logger = logging.getLogger("notulen")

# Stale-recording cutoff: anything in status='recording' older than this gets
# auto-aborted. 6 hours covers any plausible real meeting.
STALE_RECORDING_HOURS = 6


def cleanup_stale_recordings_loop() -> None:
    """Poll hourly for ``recording`` sessions older than STALE_RECORDING_HOURS.

    Hands each one to ``retire_stale_session``. Frees the queue slot so a
    forgotten/closed browser session can't park the dashboard at the
    concurrent-job cap forever.
    """
    while True:
        try:
            conn = get_db()
            if conn:
                try:
                    ensure_jobs_table(conn)
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT id FROM notulen_jobs "
                            "WHERE status = 'recording' "
                            f"AND created_at < NOW() - INTERVAL '{STALE_RECORDING_HOURS} hours'"
                        )
                        stale = [str(row[0]) for row in cur.fetchall()]
                finally:
                    conn.close()
                for job_id in stale:
                    logger.info("Retiring stale recording session %s", job_id)
                    retire_stale_session(job_id)
        except Exception:
            # Tier-2 swallow (documented): the daemon must survive transient
            # DB outages; the next hourly tick retries the same rows.
            logger.exception("cleanup-stale-recordings loop error")
        time.sleep(3600)
