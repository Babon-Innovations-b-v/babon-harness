"""The assistant's door: alert triage, the notify pen, patrol, and the MCP
tool door the OpenClaw gateway calls.

Module map:
    entrypoints/  uvicorn launcher; the container's only runtime entry
    gates/        FastAPI app, MCP door, per-source shape adapters, auth
    core/         the decisions (triage, flush, patrol, compact), the tool
                  registry and the SQLite state package
    shared/       auth, Signal and Talk sending, the Anthropic client and
                  pricing, the budget, and the name, zone and project settings
    workspace/    the prose and config handed to the gateway, and apply.sh
    watch/        passes that watch the assistant from outside its container
    mcp/          MCP servers for a Claude session (calendars)
    ops/          operator scripts (secret rotation, Signal backup)

Triage pipeline:
    Alertmanager webhook
      -> gates.app (schema check + shared-secret auth)
      -> core.triage (decision, model tool use, budget cap, dedup)
      -> the notify pen -> shared.signal (signal-cli) or silent

The interface is HTTP; nothing in the repository imports this package, so the
root seam re-exports nothing.

FAILURE POLICY: two-tier. The model lanes are Tier-2 degrade-never-drop, each
swallow defended at its site. State writes are Tier-1 fail-loud: a failed
write fails the webhook so the sender retries.
"""
from __future__ import annotations

__all__: list[str] = []
