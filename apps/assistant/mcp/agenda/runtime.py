"""ensure_client(), process-global lazy CalDAV client cache.

Owns lazy init only: the first tool call pays the auth cost (one
principal request), keeping the import-time path cheap so the
MCP framework's stdio handshake completes promptly. Does NOT own the tool
surface (``tools/``) or the transport (``server.py``).

Tests monkeypatch ``_client`` here (the declared test seam) instead of
patching tool internals.

FAILURE POLICY: fail-loud, SecretsUnavailable / the AgendaClient auth
RuntimeError propagate to the calling tool, which surfaces them as MCP tool
errors; no silent fallback calendars.
"""
from __future__ import annotations

from .client import AgendaClient
from .secrets import load_credentials

_client: AgendaClient | None = None


def ensure_client() -> AgendaClient:
    """Lazy-init the CalDAV client on first tool call."""
    global _client
    if _client is None:
        credentials = load_credentials()
        _client = AgendaClient(credentials)
    return _client
