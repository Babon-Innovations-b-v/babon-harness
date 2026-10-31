"""Who is behind a request, read from the single sign-on headers.

The dashboard sits behind oauth2-proxy, which signs people in against the
Nextcloud single sign-on and hands every request on with ``Remote-User`` and
``Remote-Email`` set by Caddy. The dashboard reads those two headers and
nothing else: no Basic auth, no session of its own.

FAILURE POLICY: pure header reads. Falls back to "anonymous" rather than
refusing, because Caddy only forwards signed-in requests and a write that
lands unattributed is better than one refused because a header moved.
"""
from __future__ import annotations

from fastapi import Request


def who(request: Request) -> str:
    """The signed-in person's stable name: ``Remote-User``, else the email."""
    headers = request.headers
    return (
        (headers.get("Remote-User") or "").strip()
        or (headers.get("Remote-Email") or "").strip()
        or "anonymous"
    )
