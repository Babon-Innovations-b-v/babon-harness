"""Git publication of generated notulen (``core/publish/``).

``complete`` means committed to git, not merely transcribed.

Module map (one public callable per file):
    github/attendee_name.py          : attendee_name(attendees) -> the who half of the name
    github/target_path.py            : target_path(meeting_date, title, attendees) -> repo path
    github/api_session.py            : github_session(): the token + headers, once
    github/github_writer.py          : commit_notulen_to_github(...) -> Committed(url, path)
                                        via the Contents API; never overwrites
    github/read_notulen.py           : read_notulen(path) -> (markdown, sha)
    github/rewrite_notulen.py        : rewrite_notulen(...): the one door that
                                        replaces a file, for a person's correction
    github/remove_notulen.py         : remove_notulen(path, message): take the
                                        minutes out when a run is deleted
    retry/finalize_commit.py         : finalize_commit(...): commit then mark complete
    retry/stuck_commits.py           : stuck_committing_ids(rows, now): page-worthy strands
    retry/alert_stuck_committing.py  : alert_stuck_committing(job_ids): throttled ops page
    retry/git_writer_loop.py         : git_writer_loop() 30s daemon (GPU-path catch-up)
"""
from __future__ import annotations

from apps.notulen.app.core.publish.retry.alert_stuck_committing import (
    alert_stuck_committing,
)
from apps.notulen.app.core.publish.retry.finalize_commit import finalize_commit
from apps.notulen.app.core.publish.retry.git_writer_loop import git_writer_loop
from apps.notulen.app.core.publish.github.github_writer import (
    commit_notulen_to_github,
)
from apps.notulen.app.core.publish.retry.stuck_commits import (
    STUCK_COMMIT_THRESHOLD_SEC,
    stuck_committing_ids,
)
from apps.notulen.app.core.publish.github.target_path import target_path

__all__ = [
    "STUCK_COMMIT_THRESHOLD_SEC",
    "alert_stuck_committing",
    "commit_notulen_to_github",
    "finalize_commit",
    "git_writer_loop",
    "stuck_committing_ids",
    "target_path",
]
