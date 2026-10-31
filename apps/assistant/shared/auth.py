"""Shared-secret bearer auth for webhook gates.

Alertmanager + Sentry won't bring an OAuth token. They sign their POST
with a fixed shared secret in the `Authorization: Bearer <secret>`
header (this is the form AM v2 `http_config.authorization` emits, so we
don't have to invent a custom header).

The shared secret is OPENCLAW_WEBHOOK_SECRET in the owner's vault env file
(`config/vault.env.example`) and reaches the container through compose. Constant-time compare
so a malicious caller can't time-side-channel one byte at a time.

Single public callable: `verify(authorization_header)`.

ROTATION: a request is accepted if it matches EITHER the current
`OPENCLAW_WEBHOOK_SECRET` or, when set, `OPENCLAW_WEBHOOK_SECRET_PREV`
,  the same primary+fallback carousel as the JWT/Django keys. This makes
the webhook secret zero-downtime rotatable: set PREV = the old secret,
swap the primary to the new one, update Alertmanager, then clear PREV.
During the swap both the old (AM, until it's updated) and new bearers
verify, so there is no 401 window and no missed alert.

FAILURE POLICY: fail-closed loud. Missing/garbled headers return
False (request gets a 401). An unset `OPENCLAW_WEBHOOK_SECRET` raises
`RuntimeError` at request time, every request 500s rather than one
request of "temporarily allow all".
"""
from __future__ import annotations

import hmac
import os

_ENV_VAR = "OPENCLAW_WEBHOOK_SECRET"
_PREV_ENV_VAR = "OPENCLAW_WEBHOOK_SECRET_PREV"


def _expected_secret() -> str:
    secret = os.environ.get(_ENV_VAR, "")
    if not secret:
        raise RuntimeError(
            f"{_ENV_VAR} not set, webhook gate will reject every request. "
            f"Set it in the vault env file and push it with infra/secrets/push-env.sh."
        )
    return secret


def _extract_bearer(header_value: str | None) -> str | None:
    if header_value is None:
        return None
    parts = header_value.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip()


def verify(authorization_header: str | None) -> bool:
    presented = _extract_bearer(authorization_header)
    if presented is None:
        return False
    # Current secret must always be set (fail-loud). The previous secret is
    # optional and only present mid-rotation. Check BOTH constant-time so a
    # rotation never opens a 401 window; the OR of two constant-time compares
    # is still not byte-by-byte guessable.
    match_current = hmac.compare_digest(presented, _expected_secret())
    prev = os.environ.get(_PREV_ENV_VAR, "")
    match_prev = bool(prev) and hmac.compare_digest(presented, prev)
    return match_current or match_prev
