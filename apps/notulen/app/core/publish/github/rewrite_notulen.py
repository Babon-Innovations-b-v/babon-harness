"""Replace a committed notulen in place, after a person corrected it.

This is the one path in this package that is ALLOWED to overwrite, and it
is a separate file for exactly that reason. `github_writer.py` refuses to
replace anything: it walks `-2`, `-3` to a free path, because a re-run must
never write over a corrected set of minutes and a second meeting never over
a first. Correcting a file is the case where writing over it is the
whole point, so it gets its own door rather than a flag on that one, and
first publication can never reach this door by accident.

Overwriting safely means saying which version you are replacing. The caller
passes the blob sha it read, and GitHub refuses the write when the file has
moved on since, so two people editing the same minutes collide instead of
losing one of the two edits.

FAILURE POLICY: Tier-1: raises. A save that cannot commit must reach the
person who pressed save, never be swallowed into a page that looks saved.
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



class NotulenMovedOn(RuntimeError):
    """The file changed since it was read, so this save would lose that change."""


def rewrite_notulen(
    path: str,
    markdown: str,
    sha: str,
    message: str,
    *,
    token: Optional[str] = None,
    session: Optional[requests.Session] = None,
) -> str:
    """Commit `markdown` over the file at `path`; return the commit URL.

    `sha` is the blob sha the editor was given, from `read_notulen`.

    Raises:
        ValueError: on an empty path, empty sha, or empty markdown. Saving
            nothing over a set of minutes is never a real edit, and this is
            the last place that can tell.
        NotulenMovedOn: the file moved on since it was read (GitHub 409).
        KeyError: no usable token (see `api_session`).
        requests.HTTPError: any other non-2xx.
    """
    if not path or not sha:
        raise ValueError("rewrite_notulen needs the path and the sha it is replacing")
    if not markdown.strip():
        raise ValueError("refusing to commit empty minutes over an existing file")

    http, headers = github_session(token=token, session=session)
    url = f"{API_ROOT}/repos/{target_repo()}/contents/{path}"
    response = http.put(url, headers=headers, json={
        "message": message,
        "content": base64.b64encode(markdown.encode("utf-8")).decode("ascii"),
        "sha": sha,
        "branch": target_branch(),
    })
    if response.status_code == 409:
        raise NotulenMovedOn(
            f"{path} changed since it was opened; reload and reapply the edit"
        )
    response.raise_for_status()
    return response.json()["commit"]["html_url"]
