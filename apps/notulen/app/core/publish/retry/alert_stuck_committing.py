"""Page for minutes stranded uncommitted in Postgres.

Owns the page copy and the in-process throttle. Does NOT own stuck detection
(``stuck_commits.py``) or the retry itself (``git_writer_loop.py``).

FAILURE POLICY: documented Tier-2 swallow: a broken page path must never
break the commit loop. Throttled in-process to one page per hour, so a
multi-day credential outage pages once an hour rather than every 30 s poll;
a container restart resets the throttle, which is itself worth a page.
``notifier`` is injectable so a test can capture the page.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable

from apps.notulen.app.core.publish.retry.stuck_commits import (
    STUCK_COMMIT_THRESHOLD_SEC,
)
from apps.notulen.app.shared.assistant_door import notify_assistant
from apps.notulen.app.shared.config import target_folder

logger = logging.getLogger("notulen")

_STUCK_COMMIT_ALERT_THROTTLE_SEC = 3600
_last_stuck_commit_alert_ts: float = 0.0


def alert_stuck_committing(
    job_ids: list[str],
    *,
    notifier: Callable[[str, str], None] = notify_assistant,
    now: Callable[[], float] = time.time,
) -> None:
    """Page when minutes are stranded uncommitted in Postgres."""
    global _last_stuck_commit_alert_ts
    current = now()
    if current - _last_stuck_commit_alert_ts < _STUCK_COMMIT_ALERT_THROTTLE_SEC:
        return
    _last_stuck_commit_alert_ts = current
    try:
        notifier(
            "notulen: minutes stuck uncommitted in Postgres",
            f"{len(job_ids)} notulen job(s) have minutes but cannot commit "
            f"to {target_folder()}/ for more than {STUCK_COMMIT_THRESHOLD_SEC // 60} min.\n"
            f"Jobs: {', '.join(job_ids[:10])}\n\n"
            "Almost always GITHUB_NOTULEN_PAT (missing, expired, or without "
            "contents write on NOTULEN_TARGET_REPO). Fix it in the vault; the "
            "markdown is safe in notulen_jobs.output_markdown and commits by "
            "itself once the token works. Throttled to one page per hour.",
        )
    except Exception:
        # Documented Tier-2 swallow (see module FAILURE POLICY).
        logger.exception("Failed to page on stuck-committing notulen jobs")
