"""Read a committed notulen back out of the repository.

The edit surface shows the FILE, not the database row. A save writes the
file and deliberately leaves `notulen_jobs.output_markdown` as the machine's
untouched first draft, so the row stops being the current text the moment
anybody corrects anything; showing it in the editor would hand the team the
draft they already fixed. This reads the real one.

It reads through the API rather than any local clone, because a clone only
catches up on the next deploy cycle. Someone who saves and reloads must see
what they saved.

FAILURE POLICY: Tier-1: raises. A read that fails must not render an empty
editor, because saving that would blank the minutes.
"""
from __future__ import annotations

import base64
from typing import Optional

import requests

from apps.notulen.app.core.publish.github.api_session import (
    API_ROOT,
    github_session,
)
from apps.notulen.app.shared.config import target_branch, target_repo



def read_notulen(
    path: str,
    *,
    token: Optional[str] = None,
    session: Optional[requests.Session] = None,
) -> tuple[str, str]:
    """Return `(markdown, sha)` for a committed notulen at `path`.

    The blob sha comes back with it because a save has to prove it is
    replacing the version it was handed: two people editing the same
    minutes should collide, not silently overwrite each other.

    Raises:
        KeyError: no usable token (see `api_session`).
        FileNotFoundError: nothing is committed at that path.
        requests.HTTPError: any other non-2xx.
    """
    http, headers = github_session(token=token, session=session)
    url = f"{API_ROOT}/repos/{target_repo()}/contents/{path}"
    response = http.get(url, headers=headers, params={"ref": target_branch()})
    if response.status_code == 404:
        raise FileNotFoundError(f"no notulen committed at {path}")
    response.raise_for_status()
    payload = response.json()
    markdown = base64.b64decode(payload["content"]).decode("utf-8")
    return markdown, payload["sha"]
