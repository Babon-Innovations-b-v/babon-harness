"""The signed-in user, as the single sign-on hands it over.

Every SSO-gated dashboard sits behind Caddy's ``oauth2_auth`` snippet:
Caddy asks oauth2-proxy whether the request carries a valid login
cookie, and on yes copies oauth2-proxy's ``X-Auth-Request-User`` and
``X-Auth-Request-Email`` into the request as ``Remote-User`` and
``Remote-Email``. The same snippet strips any client-sent copy of those
headers first, so a dashboard can trust them. The login itself happened
at Nextcloud; nothing here sees a password.
"""
from __future__ import annotations

from typing import Mapping, Optional

ANONYMOUS = "anonymous"


def get_user(headers: Optional[Mapping[str, str]]) -> str:
    """Return the SSO user id from request headers.

    ``Remote-User`` first (the stable account id), then ``Remote-Email``.
    Returns ``"anonymous"`` when neither is present. Never raises: a
    missing header only costs attribution, and the activity row records
    the anonymous fact. Routes that must refuse anonymous callers check
    for ``"anonymous"`` themselves.
    """
    if not headers:
        return ANONYMOUS
    for name in ("Remote-User", "Remote-Email"):
        value = (headers.get(name) or "").strip()
        if value:
            return value
    return ANONYMOUS
