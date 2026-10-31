"""Webhook receivers, FastAPI app + per-source shape adapters.

Module map:
    app.py           the FastAPI app: /health, /webhook/alertmanager,
                     /webhook/notify (uvicorn addresses
                     it by dotted path `gates.app:app`; not re-exported
                     here to keep gate-adapter imports free of FastAPI/core
                     weight)
    mcp.py           the MCP tool door: the assistant's read-only tools served over
                     streamable-http at POST /mcp, bearer-gated, built by
                     `assistant_mcp_door()` and routed by app.py. Not
                     re-exported here for the same reason app.py is not: it
                     pulls in the whole tool registry
    alertmanager.py  AM v4 envelope -> list[Alert]
    notify.py        pass-through notify body -> Notification
    e164.py          shared sender-number normalisation

Adapters convert the inbound payload into core types and nothing else.
The gate is a thin shape, no decision logic, no DB, no LLM.

FAILURE POLICY: fail-closed at the edge, bad secret 401, malformed
payload 400 (`ValueError` from the parse adapters), unlisted sender
dropped before any LLM call. Details per module.
"""
from __future__ import annotations

from apps.assistant.gates.e164 import normalize_number
from apps.assistant.gates.notify import Notification

__all__ = ["Notification", "normalize_number"]
