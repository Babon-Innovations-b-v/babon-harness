"""The Nextcloud account notulen uses to reach Talk: its base URL and login.

The assistant's account owns every call room it creates, which makes it the
moderator who may start a recording, and the recording server stores the
finished file in that account's Files. So notulen acts as the same account,
with the same app password the assistant's calendar and Talk code use:
``NC_URL`` (the Nextcloud base), ``AGENDA_USER`` and ``AGENDA_APP_PASSWORD``.

FAILURE POLICY: fail-loud. A missing login raises, because every caller is
on a path where acting without it would lose a meeting silently.
"""
from __future__ import annotations

import base64
import os


def nc_base() -> str:
    """The Nextcloud base URL, without a trailing slash."""
    base = os.environ.get("NC_URL", "").strip().rstrip("/")
    if not base:
        raise RuntimeError("NC_URL not set; cannot reach Nextcloud Talk")
    return base


def talk_user() -> str:
    """The Nextcloud account that owns the call rooms."""
    user = os.environ.get("AGENDA_USER", "").strip()
    if not user:
        raise RuntimeError("AGENDA_USER not set; cannot reach Nextcloud Talk")
    return user


def basic_auth() -> str:
    """The ``Authorization`` header value for that account."""
    password = os.environ.get("AGENDA_APP_PASSWORD", "").strip()
    if not password:
        raise RuntimeError("AGENDA_APP_PASSWORD not set; cannot reach Nextcloud Talk")
    return "Basic " + base64.b64encode(f"{talk_user()}:{password}".encode()).decode()
