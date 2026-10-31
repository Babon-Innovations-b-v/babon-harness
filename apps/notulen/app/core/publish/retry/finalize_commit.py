"""Commit a notulen's markdown to git and, only on success, mark it complete.

Owns the invariant: ``complete`` means the minutes reached git, never set
without a commit URL. Does NOT own the retry
schedule (``git_writer_loop.py``) or the GitHub call itself
(``github/github_writer.py``).

FAILURE POLICY: the commit failure is a documented Tier-2 swallow AT THIS
SEAM ONLY: it converts to the ``None`` return so the job stays
``committing`` for the retry loop. The
``complete`` status write is Tier-1 and propagates.
"""
from __future__ import annotations

import logging

from apps.notulen.app.core.publish.github.github_writer import (
    commit_notulen_to_github,
)
from apps.notulen.app.shared.update_job import update_job

logger = logging.getLogger("notulen")


def finalize_commit(
    job_id: str,
    title: str,
    meeting_date: str,
    notulen_md: str,
    attendees: list[str],
    *,
    committer=commit_notulen_to_github,
    updater=update_job,
) -> str | None:
    """Returns the commit URL, or None if the commit failed (the job stays
    ``committing`` for ``git_writer_loop`` to retry). Crucially never marks a
    job ``complete`` without a commit URL. ``committer``/
    ``updater`` are injectable collaborators for tests.

    The path is recorded beside the URL because the slot walk means it is not
    derivable from the title and the date, and it is what the edit surface
    reopens when somebody corrects these minutes.
    """
    try:
        committed = committer(job_id, title, meeting_date, notulen_md, attendees)
    except Exception:
        logger.exception(
            "GitHub commit failed for job %s; staying 'committing', git_writer_loop will retry",
            job_id,
        )
        return None
    updater(
        job_id,
        status="complete",
        output_commit_url=committed.url,
        output_path=committed.path,
    )
    return committed.url
