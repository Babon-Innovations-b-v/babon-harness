"""Daemon loop that commits ``committing`` jobs to GitHub.

Catch-up for the GPU path: the worker writes ``committing`` rows from the
cluster (it has no commit credential), then this dashboard-side loop commits the
markdown and flips the row to ``complete`` via ``finalize_commit``. Also
retries CPU-path jobs whose inline commit failed.

The select has NO time window: the commit is idempotent and cheap, so a job
stays retriable until it lands no matter how long the credential outage runs.
A job stuck past the threshold pages the assistant (``stuck_commits.py``)
instead of silently ageing out.

FAILURE POLICY: Tier-2 loop: each 30s tick swallows + logs and retries on
the next tick; the complete-means-committed invariant is enforced
inside ``finalize_commit``, not here.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from dashkit.core.db import get_db

from apps.notulen.app.core.publish.retry.alert_stuck_committing import (
    alert_stuck_committing,
)
from apps.notulen.app.core.publish.retry.finalize_commit import finalize_commit
from apps.notulen.app.core.publish.retry.stuck_commits import (
    stuck_committing_ids,
)
from apps.notulen.app.shared.jobs_table import ensure_jobs_table

logger = logging.getLogger("notulen")

_COMMITTING_SELECT_SQL = (
    "SELECT id, title, meeting_date, output_markdown, attendees, "
    "COALESCE(completed_at, created_at) "
    "FROM notulen_jobs "
    "WHERE status = 'committing' "
    "AND output_markdown IS NOT NULL "
    "AND output_commit_url IS NULL"
)


def git_writer_loop() -> None:
    """Every 30s, commit ``committing`` jobs to GitHub and page if any stick."""
    while True:
        try:
            conn = get_db()
            if conn:
                try:
                    ensure_jobs_table(conn)
                    with conn.cursor() as cur:
                        cur.execute(_COMMITTING_SELECT_SQL)
                        rows = cur.fetchall()
                finally:
                    conn.close()

                still_uncommitted: list[tuple[str, datetime]] = []
                for job_id, title, meeting_date, markdown, attendees, awaiting_since in rows:
                    job_id_str = str(job_id)
                    date_str = (
                        meeting_date.isoformat()
                        if hasattr(meeting_date, "isoformat")
                        else str(meeting_date)
                    )
                    commit_url = finalize_commit(
                        job_id_str, title, date_str, markdown, list(attendees or [])
                    )
                    if commit_url:
                        logger.info("git-writer committed %s: %s", job_id_str, commit_url)
                    else:
                        still_uncommitted.append((job_id_str, awaiting_since))

                stuck = stuck_committing_ids(
                    still_uncommitted, datetime.now(timezone.utc)
                )
                if stuck:
                    alert_stuck_committing(stuck)
        except Exception:
            # Tier-2 swallow (documented): the daemon must survive transient
            # DB/GitHub outages; the next 30s tick retries everything.
            logger.exception("git-writer loop error")
        time.sleep(30)
