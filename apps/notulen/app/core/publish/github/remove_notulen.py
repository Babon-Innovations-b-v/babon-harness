"""Take the committed minutes out of the repository when a run is deleted.

A file left behind by a deleted recording is invisible from the dashboard and
still holds its name, so the next real meeting that day with the same people
would land on `-2` instead.

BE HONEST ABOUT WHAT THIS DOES. It removes the file from the branch, which is
a commit. The content stays in the history, so this is tidying rather than
erasure; anything that has to be genuinely unrecoverable needs a different
mechanism and a decision to go with it.

FAILURE POLICY: Tier-2, and deliberately the opposite of the audio delete
next to it. The recording is privacy-relevant and its delete fails the whole
request; a leftover markdown file is untidy, so a GitHub outage must not stop
somebody removing a recording. It returns whether the file went, and the
caller says so.
"""
from __future__ import annotations

import logging
from typing import Optional

import requests

from apps.notulen.app.core.publish.github.api_session import (
    API_ROOT,
    github_session,
)
from apps.notulen.app.shared.config import target_branch, target_repo

logger = logging.getLogger("notulen")



def remove_notulen(
    path: str,
    message: str,
    *,
    token: Optional[str] = None,
    session: Optional[requests.Session] = None,
) -> bool:
    """Delete the file at `path` from `main`; True when it is gone.

    True is also the answer when there was nothing there, because the caller
    asked for the file to be absent and it is. False means it is still there
    and somebody has to look.
    """
    if not path:
        return True
    try:
        http, headers = github_session(token=token, session=session)
        url = f"{API_ROOT}/repos/{target_repo()}/contents/{path}"
        found = http.get(url, headers=headers, params={"ref": target_branch()})
        if found.status_code == 404:
            return True
        found.raise_for_status()
        # The sha names the version being removed, so a file somebody edited
        # between the read and the delete refuses rather than vanishing.
        removed = http.delete(url, headers=headers, json={
            "message": message,
            "sha": found.json()["sha"],
            "branch": target_branch(),
        })
        removed.raise_for_status()
        return True
    except (KeyError, requests.RequestException) as exc:
        logger.warning("could not remove %s from the repository: %s", path, exc)
        return False
