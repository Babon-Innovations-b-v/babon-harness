"""A Talk webhook whose signature does not match the bot secret is refused.

WHAT IT PINS. `POST /api/talk/webhook` in `app/entrypoints/talk_routes.py`. The
route sits outside the single sign-on, so the HMAC signature is the only thing
standing between the internet and "start recording this room". A forged or
unsigned event must get 401 and start nothing.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From Nextcloud
Talk's bot documentation: the signature is the hex HMAC-SHA256 of the
`X-Nextcloud-Talk-Random` header followed by the raw body, keyed with the bot
secret. The test computes that with `hmac` itself, signs one event with the
right secret and one with a wrong secret, and sends one with no headers. Only
the first may pass the gate; its event names no room, so it is answered
`ignored` and nothing is started.

WHAT IT WAS PROVED AGAINST. Comparing the signature against the digest of the
body alone, without the random header, so the correctly signed event is
refused and the first assertion trips.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os

# A placeholder DSN for anything that resolves one at import. Nothing here
# opens a connection.
os.environ.setdefault("DB_URL", "postgresql://test/none")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from apps.notulen.app.entrypoints.talk_routes import router  # noqa: E402

_SECRET = "the-bot-secret"
_RANDOM = "a-random-nonce"


def _signature(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), _RANDOM.encode() + body, hashlib.sha256).hexdigest()


def test_a_talk_webhook_whose_signature_does_not_match_the_bot_secret_is_refused(monkeypatch) -> None:
    """Right secret passes the gate; wrong secret and no signature are 401."""
    monkeypatch.setenv("TALK_BOT_SECRET", _SECRET)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    body = json.dumps({"object": {"name": "call_started"}, "target": {}}).encode()

    signed = client.post(
        "/api/talk/webhook",
        content=body,
        headers={
            "X-Nextcloud-Talk-Random": _RANDOM,
            "X-Nextcloud-Talk-Signature": _signature(_SECRET, body),
        },
    )
    assert signed.status_code == 200
    assert signed.json() == {"ok": True, "ignored": "no room token"}

    forged = client.post(
        "/api/talk/webhook",
        content=body,
        headers={
            "X-Nextcloud-Talk-Random": _RANDOM,
            "X-Nextcloud-Talk-Signature": _signature("not-the-secret", body),
        },
    )
    assert forged.status_code == 401

    unsigned = client.post("/api/talk/webhook", content=body)
    assert unsigned.status_code == 401
