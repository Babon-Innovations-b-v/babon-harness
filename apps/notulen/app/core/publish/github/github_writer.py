"""Commit minutes markdown to the target repository via the GitHub Contents API.

The one write path: this module, then GitHub, then whatever reads the
repository (the deploy loop's clone, a person's checkout). The repository is
``NOTULEN_TARGET_REPO`` and the branch ``NOTULEN_TARGET_BRANCH`` (default
``main``).

Idempotent: the same content already committed is a no-op. It never replaces
a file that is already there, because minutes are a record: a second meeting
on the same day with the same people, or a job re-run over the same audio,
lands beside the first as ``-2`` rather than over it. Does NOT own when or
whether to commit: that policy lives in ``retry/finalize_commit.py`` and
``retry/git_writer_loop.py``.

FAILURE POLICY: Tier-1. Raises (KeyError on a missing token,
requests.HTTPError on a non-2xx); callers keep the job ``committing`` and
retry.
"""
from __future__ import annotations

import base64
from typing import NamedTuple, Optional

import requests

from apps.notulen.app.core.publish.github.api_session import (
    API_ROOT,
    github_session,
)
from apps.notulen.app.core.publish.github.target_path import target_path
from apps.notulen.app.shared.config import target_branch, target_repo

# a day with more than this many meetings between the same people is a bug,
# not a schedule
MAX_SAME_DAY_MEETINGS = 12


class Committed(NamedTuple):
    """Where the minutes landed: the URL for a person, the path for a machine.

    The path is what lets anything ever find the file again. Without it the
    only record of where a notulen went was a commit URL, and the slot walk
    means the path is not derivable from the title and the date: the second
    meeting of a day lands on `-2`. Recording it is what makes correcting a
    notulen possible at all.
    """

    url: str
    path: str


def commit_notulen_to_github(
    job_id: str,
    title: str,
    meeting_date: str,
    output_markdown: str,
    attendees: list[str],
    *,
    token: Optional[str] = None,
    session: Optional[requests.Session] = None,
) -> Committed:
    """Commit (or no-op) the notulen markdown; return where it landed.

    `url` is the commit URL on a real write, or the file URL when the call
    was idempotent (content already matches). Callers store both against the
    job row: the URL for the audit trail, the path so the file can be read
    back and corrected.

    Raises:
        KeyError: if no token is passed and GITHUB_NOTULEN_PAT is not set,
            or no target repository is configured.
        requests.HTTPError: if the GitHub API returns a non-2xx on PUT.
    """
    http, headers = github_session(token=token, session=session)

    api_url, path, idempotent_url = _free_slot(
        http, headers, meeting_date, title, attendees, output_markdown
    )
    if idempotent_url is not None:
        return Committed(idempotent_url, path)

    resp = http.put(api_url, headers=headers, json={
        "message": _commit_message(title, meeting_date, job_id),
        "content": base64.b64encode(output_markdown.encode("utf-8")).decode("ascii"),
        "branch": target_branch(),
    })
    resp.raise_for_status()
    return Committed(resp.json()["commit"]["html_url"], path)


def _free_slot(
    http: requests.Session,
    headers: dict,
    meeting_date: str,
    title: str,
    attendees: list[str],
    output_markdown: str,
) -> tuple[str, str, Optional[str]]:
    """Find a path to write to that destroys nothing.

    Returns ``(api_url, path, idempotent_url)``. When ``idempotent_url`` is set
    the exact content is already committed somewhere and the caller writes
    nothing; ``path`` still names where it is, because that is the file a
    later correction has to reopen.

    Two meetings can share a day and their attendees, and a written file may
    also have been corrected by hand afterwards. Either way the file that is already
    there is a record, so this never replaces it: it walks ``-2``, ``-3`` until
    it finds a path that is free, or one that already holds exactly this
    content, which keeps a retry from committing the same minutes twice.
    """
    base = target_path(meeting_date, title, attendees)
    for attempt in range(1, MAX_SAME_DAY_MEETINGS + 1):
        path = base if attempt == 1 else f"{base[:-len('.md')]}-{attempt}.md"
        api_url = f"{API_ROOT}/repos/{target_repo()}/contents/{path}"
        taken, idempotent_url = _read_existing_for_idempotency(
            http, api_url, headers, output_markdown
        )
        if idempotent_url is not None:
            return api_url, path, idempotent_url
        if not taken:
            return api_url, path, None
    raise RuntimeError(
        f"No free path for {base}: {MAX_SAME_DAY_MEETINGS} files already exist "
        "for this day and these people, which is not a real meeting pattern"
    )


def _commit_message(title: str, meeting_date: str, job_id: str) -> str:
    """Human-readable, audit-friendly commit message tying file → job.

    The `[job:<id>]` tag traces a file back to its row in `notulen_jobs`.
    """
    return f"notulen: {title} ({meeting_date}) [job:{job_id}]"


def _read_existing_for_idempotency(
    http: requests.Session,
    api_url: str,
    headers: dict,
    new_markdown: str,
) -> tuple[bool, Optional[str]]:
    """Return (taken, idempotent_url) for one candidate path.

    `taken` is True when something is already committed there. Nothing here
    ever updates a file in place, so whether the path is occupied is the only
    question; the caller moves to the next candidate.

    `idempotent_url` is non-None only when the existing content already
    matches the new content: in that case callers skip the PUT entirely
    and return this URL as the result.
    """
    resp = http.get(api_url, headers={**headers, "Accept": "application/vnd.github+json"})
    if resp.status_code == 404:
        return False, None
    if resp.status_code != 200:
        resp.raise_for_status()

    body = resp.json()

    encoded = body.get("content", "")
    if body.get("encoding") == "base64":
        existing_bytes = base64.b64decode(encoded)
    else:
        existing_bytes = encoded.encode("utf-8")

    if existing_bytes == new_markdown.encode("utf-8"):
        return True, body.get("html_url") or api_url

    return True, None
