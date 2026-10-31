"""Detect notulen markdown stranded uncommitted in Postgres.

Owns the stuck threshold and the detection. Does NOT own the ops page
(``alert_stuck_committing.py``) or the retry itself
(``git_writer_loop.py``).

FAILURE POLICY: ``stuck_committing_ids`` is pure (no DB, no clock: caller
passes ``now`` so tests pin it); nothing to swallow.
"""
from __future__ import annotations

from datetime import datetime

# A job whose markdown has been awaiting its git commit longer than this is
# stuck (a broken or absent GITHUB_NOTULEN_PAT, a GitHub outage). Pages.
# 15 min is far longer than a healthy commit (seconds) yet well inside any
# plausible deploy or secret-sync blip.
STUCK_COMMIT_THRESHOLD_SEC = 15 * 60


def stuck_committing_ids(rows, now: datetime) -> list[str]:
    """Job IDs whose markdown has been awaiting commit past the threshold.

    ``rows`` is an iterable of ``(job_id, awaiting_since)`` where
    ``awaiting_since`` is when the markdown became ready (completed_at,
    falling back to created_at).
    """
    stuck: list[str] = []
    for job_id, awaiting_since in rows:
        if awaiting_since is None:
            continue
        if (now - awaiting_since).total_seconds() > STUCK_COMMIT_THRESHOLD_SEC:
            stuck.append(str(job_id))
    return stuck
