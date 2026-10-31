"""What the assistant can actually do, the capability block.

A model that is never shown its own access confabulates it, for example
denying write access to a calendar it manages. The scope registry knows
team/alex and their read/write calendars, so it is rendered into the prompt.
`render(sender)` turns `calendars.scopes()` into ground truth the chat loop
pastes in, plus a speaker->scope bridge so "my agenda" resolves to a real
calendar instead of a guess. Facts, not belief.

Single public callable: `render(sender, sender_uuid)`.

FAILURE POLICY: Tier-2, every read is defended; a fault yields an empty
block, never an error (a missing capability block must not break chat). It is
pasted like principles/voice/awareness.
"""
from __future__ import annotations

import logging
import os

from apps.assistant.core import people
from apps.assistant.core.tools.agenda import calendars

log = logging.getLogger("openclaw.capabilities")

_AGENDA_WRITE_ENV = "ASSISTANT_AGENDA_WRITE"


def render(sender: str | None = None, sender_uuid: str | None = None) -> str:
    """The 'what you can actually do' block for the chat system prompt: the
    calendars the assistant manages (read vs write, per scope) and, when it knows who
    it is talking to, which calendar their 'my agenda' means."""
    try:
        scopes = calendars.scopes()
    except Exception as exc:  # noqa: BLE001, Tier-2: capability block must never break chat
        log.warning("capability scope read failed: %s", exc)
        return ""
    interesting = [scope for scope in scopes.values() if _interesting(scope)]
    if not interesting:
        return ""

    writes_on = os.environ.get(_AGENDA_WRITE_ENV, "").strip() == "1"
    lines = [
        "YOUR CALENDARS, what you can actually read and write, from your live "
        "registry (do not guess your access, use this):"
    ]
    for scope in interesting:
        reads = ", ".join(cal.display for cal in scope.read)
        if scope.write is not None:
            lines.append(f"- {scope.display} (say who='{scope.name}'): read {reads}; write to {scope.write.display}.")
        else:
            lines.append(f"- {scope.display} (say who='{scope.name}'): read only ({reads}); you cannot add or remove here.")
    lines.append(
        "Agenda writing is currently ON." if writes_on
        else "Agenda writing is currently OFF, so you can read calendars but not change them; say so if asked to."
    )
    lines.append(
        "To find an event, use agenda_view who='all' (it shows every calendar and each event's id), then act with agenda_act by that id."
    )

    bridge = _speaker_bridge(sender, sender_uuid, scopes)
    if bridge:
        lines.append(bridge)
    return "\n".join(lines)


def _interesting(scope: "calendars.Scope") -> bool:
    """Show the shared team calendar and any real person scope (several read
    calendars, or a write target that differs from the scope's own key); hide
    the per-calendar self-scopes that would just repeat them."""
    return (
        scope.name == calendars.TEAM_KEY
        or len(scope.read) > 1
        or (scope.write is not None and scope.write.key != scope.name)
    )


def _speaker_bridge(sender: str | None, sender_uuid: str | None, scopes: dict) -> str:
    """Link the person the assistant is talking to their own calendar scope, so 'my
    agenda' is a resolved key, not a guess. Silent when unknown or the person
    has no personal scope."""
    if not sender:
        return ""
    person = people.identify(sender, sender_uuid)
    if person is None:
        return ""
    scope = scopes.get(person.name.strip().lower())
    if scope is None or scope.write is None:
        return ""
    return (
        f"You are talking to {person.name}: when they say 'my agenda' or 'my "
        f"calendar', that is scope '{scope.name}' and a new event goes on {scope.write.display}."
    )
