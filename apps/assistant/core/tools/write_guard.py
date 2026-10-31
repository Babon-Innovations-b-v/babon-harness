"""Shared safety shape for the assistant's OUTWARD write tools.

Every tool that changes something outside the assistant's own SQLite, the GitHub
board (`github_act`), the team calendar (`agenda_act`), a
Signal message to a teammate (`message_teammate`), wears the same
two locks:

  1. KILL SWITCH: an env flag that must be "1" or the write refuses, so the
     whole capability can be turned off instantly.
  2. AUDIT: a row in `state.assistant_actions`, written before the write is
     reported done, so every outward action is on the record.

This module is the one home for both, so a new outward tool cannot forget
either and the refusal reads the same everywhere. It is NOT for the
read-only investigation tools, nor for the assistant's own-artefact self-writes
(worklist / journal / principles / personal rules), those stay
ungated by design.

FAILURE POLICY: refusals are plain text (Tier-2, returned to the LLM); the
audit write is Tier-1 (propagates).
"""
from __future__ import annotations

import os

from apps.assistant.core import state


def refuse(reason: str) -> str:
    """The one refusal shape every write tool returns to the model."""
    return f"refused: {reason}"


def require_enabled(enable_env: str, what: str) -> str | None:
    """None when `enable_env` is "1" (the write may proceed), else a refusal
    naming the kill switch that is off. `what` is a verb phrase for the
    message, e.g. 'change the board', 'change the agenda', 'message teammates'."""
    if os.environ.get(enable_env, "") != "1":
        return refuse(f"{enable_env} is not enabled right now, so I can't {what}.")
    return None


def audit(kind: str, target: str, summary: str, actor: str, detail: str = "") -> None:
    """Record an outward write in `state.assistant_actions`. Call BEFORE the
    action is reported done, so an unrecordable action is never reported as
    taken (the state write is Tier-1 and propagates)."""
    state.record_action(kind, target, summary, actor=actor, detail=detail)
