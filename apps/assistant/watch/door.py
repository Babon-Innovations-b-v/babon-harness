"""Where the passes on the server reach the assistant's door.

The door listens inside its container and compose publishes it on the
server's loopback only, at OPENCLAW_PORT. Every pass in this package runs on
the server itself (a systemd timer), so it reaches the door there.
`ASSISTANT_DOOR_URL` overrides the whole address, for a pass that runs inside
the compose network instead (`http://assistant:8000`).
"""
from __future__ import annotations

import os


def door_url() -> str:
    """The door's base URL, without a trailing slash."""
    explicit = os.environ.get("ASSISTANT_DOOR_URL", "").strip().rstrip("/")
    if explicit:
        return explicit
    port = os.environ.get("OPENCLAW_PORT", "").strip() or "8000"
    return f"http://127.0.0.1:{port}"


BASE_URL: str = door_url()

__all__ = ["BASE_URL", "door_url"]
