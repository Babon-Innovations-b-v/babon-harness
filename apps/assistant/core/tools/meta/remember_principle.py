"""`remember_principle` tool, how the owner teaches openclaw.

When the owner corrects openclaw or tells it a rule over Signal ("stop relaying unit
refreshes", "always flag a stuck rotation"), the chat loop records it with this
tool. It lands in the `principles` state table and, from then on, shows up in
EVERY loop's prompt via `core.principles.render()`, so a lesson taught once is
applied everywhere, with no code change.

This is the ONE write the chat loop has (alongside filing issues), sanctioned
by the house rules: it writes openclaw's own operating doctrine, not infrastructure.
It is deliberately NOT in the shared tool registry, the read-only loops
(triage, patrol, notify) apply principles, only chat records them. Chat wires
it in directly.

Since an issue it is also served over the MCP door, so `taught_by` can be a
name the calling model typed rather than a verified Signal sender. That is the
widest thing on that door: what lands here goes into every loop's prompt. The
door bounds it (the name must be one the people registry holds), records every
call in `state.assistant_actions` before dispatching it, and can be switched off
whole with `ASSISTANT_DOOR_WRITE=0`; `_may_edit_global` below is still the gate on
who may teach doctrine at all.

Tool-module grammar: `NAME`, `DEFINITION`, `execute`.

FAILURE POLICY: Tier-2 in the chat loop's dispatch (a write fault returns as
text to the LLM); the underlying `state.add_principle` is Tier-1 (a failed
write propagates, never silently forget what the owner taught).
"""
from __future__ import annotations

import os
from typing import Any

from apps.assistant.core import state

NAME = "remember_principle"

# Global doctrine changes how the assistant works for EVERYONE, so only the system
# owner may set it. A personal preference from anyone else belongs in
# `personal_rule`, scoped to them. Default: the owner; override with a
# comma-separated name list.
_EDITORS_ENV = "ASSISTANT_PRINCIPLE_EDITORS"
# "owner-via-chat" is the default teacher identity (it only arises when no name
# is passed; a real sender always arrives as their own name), so it counts as
# the owner too.
_OWNER_VIA_CHAT = "owner-via-chat"


def _default_editors() -> str:
    """The owner: the people registry's name for the page recipient."""
    from apps.assistant.core import people  # lazy: avoid core-init cycle

    recipient = os.environ.get("SIGNAL_RECIPIENT", "").strip()
    person = people.identify_by_number(recipient) if recipient else None
    return ",".join(name for name in (person.name if person else "", _OWNER_VIA_CHAT) if name)


def _may_edit_global(actor: str) -> bool:
    raw = os.environ.get(_EDITORS_ENV) or _default_editors()
    editors = {name.strip().lower() for name in raw.split(",") if name.strip()}
    return actor.strip().lower() in editors

DEFINITION: dict[str, Any] = {
    "name": NAME,
    "description": (
        "Record a lasting operating principle the owner just taught you, as a general "
        "instruction to yourself; it applies in every loop from now on."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "principle": {
                "type": "string",
                "description": (
                    "The rule, e.g. 'Routine unit-refresh pings are noise; do "
                    "not relay them.'"
                ),
            },
        },
        "required": ["principle"],
    },
}


def execute(tool_input: dict[str, Any], taught_by: str = _OWNER_VIA_CHAT) -> str:
    """Record one principle. `taught_by` is the teacher's name (the chat
    loop passes the sender's people-registry name); it lands in the
    `source` column and shows in `principles.render()` attribution, so
    The owner can always see who taught what and delete it."""
    principle = str(tool_input.get("principle", "")).strip()
    if not principle:
        return "no principle text given; nothing recorded"
    if not _may_edit_global(taught_by):
        return (
            "refused: global principles change how I work for everyone, and "
            f"only the owner sets those. If {taught_by} wants a rule just for how I "
            "talk to them, use personal_rule instead."
        )
    inserted = state.add_principle(principle, source=taught_by)
    if not inserted:
        return f"already recorded (no change): {principle}"
    return f"recorded principle: {principle}"
