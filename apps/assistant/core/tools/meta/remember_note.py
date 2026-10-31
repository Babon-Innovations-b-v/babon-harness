"""`remember_note` tool, how openclaw writes its journal.

Where `remember_principle` records a durable RULE the owner teaches ("stop
relaying unit refreshes"), `remember_note` records a durable FACT worth
knowing later: a finding, an event, a thread's outcome, something about a
teammate ("disk on node-1 trending up", "the owner op vakantie t/m
vrijdag"). Notes land in the `journal` state table and show up in every
loop's prompt via `core.journal.render()`, then get folded into the weekly
compact.

Sanctioned by the house rules: openclaw's own artefact, its own
SQLite, no new IAM surface. Like `remember_principle` it is deliberately NOT
in the shared registry, only chat records notes; the other loops read them.

Tool-module grammar: `NAME`, `DEFINITION`, `execute`.

FAILURE POLICY: Tier-2 in the chat loop's dispatch (a write fault returns as
text to the LLM); the underlying `state.add_note` is Tier-1 (a failed write
propagates, never silently forget what you meant to remember).
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any

from apps.assistant.core import state

log = logging.getLogger("openclaw.remember_note")

NAME = "remember_note"

DEFINITION: dict[str, Any] = {
    "name": NAME,
    "description": (
        "Write a fact worth knowing next week into your journal: a finding, an "
        "event, an open thread, a teammate's absence. Rules for how you work go "
        "to remember_principle."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "note": {
                "type": "string",
                "description": "One or two self-contained sentences.",
            },
            "person": {
                "type": "string",
                "description": "Who it is about, if a person.",
            },
        },
        "required": ["note"],
    },
}


def execute(
    tool_input: dict[str, Any],
    source: str = "chat",
    evidence: Callable[[], Sequence[str]] | None = None,
) -> str:
    note = str(tool_input.get("note", "")).strip()
    if not note:
        return "no note text given; nothing recorded"
    unbacked = unbacked_citation_refusal(note, evidence)
    if unbacked:
        return unbacked
    person = str(tool_input.get("person", "")).strip() or None
    state.add_note(note, person=person, source=source)
    return f"noted: {note}"


def unbacked_citation_refusal(
    text: str, evidence: Callable[[], Sequence[str]] | None
) -> str | None:
    """The refusal when a memory write cites what no reading returned, or None.

    A note is read back into every later run as fact, so a stale
    sha copied from yesterday's notes can become today's deploy. Only a
    "#N" issue number or a commit sha is checked; an issue a worklist title
    already names needs no fresh read. Tier-2: with no evidence record, or one
    that cannot be read, nothing is refused, because no evidence of a wrong
    number is not evidence of one.
    """
    if evidence is None:
        return None
    from apps.assistant.core import claims

    try:
        read = tuple(evidence())
        titles = tuple(str(item["title"]) for item in state.worklist.open_items())
    except Exception as exc:  # noqa: BLE001 - Tier-2: no evidence holds nothing up
        log.warning("could not read the evidence for a memory write: %s", exc)
        return None
    unread = claims.unread_citations(text, read, titles)
    if not unread:
        return None
    return (
        f"not recorded: it cites {', '.join(unread[:8])}, which no tool answer "
        "you have read lately returned. Read it, or leave it out."
    )
