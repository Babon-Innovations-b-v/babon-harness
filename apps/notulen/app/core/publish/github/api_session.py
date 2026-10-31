"""One authenticated session for the GitHub Contents API.

Owns the token choice and the request headers, and nothing else. Four files
in this directory speak to the same API (write the minutes, read them back,
replace them after an edit, remove them), and a token resolved in four places
drifts. The token is ``GITHUB_NOTULEN_PAT``: a fine-grained token with
contents write on ``NOTULEN_TARGET_REPO`` and nothing else.

FAILURE POLICY: Tier-1: a missing token raises `KeyError`, because every
caller here is a write or a read the caller cannot proceed without.
"""
from __future__ import annotations

import os
from typing import Optional

import requests

#: Public API root, so a test can point the callers at a fake.
API_ROOT = "https://api.github.com"


def github_session(
    *, token: Optional[str] = None, session: Optional[requests.Session] = None
) -> tuple[requests.Session, dict]:
    """Return `(session, headers)` ready for a Contents API call.

    Raises:
        KeyError: if no token is passed and `GITHUB_NOTULEN_PAT` is not set.
    """
    if token is None:
        token = os.environ.get("GITHUB_NOTULEN_PAT", "").strip()
        if not token:
            raise KeyError("GITHUB_NOTULEN_PAT")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    return session or requests.Session(), headers
