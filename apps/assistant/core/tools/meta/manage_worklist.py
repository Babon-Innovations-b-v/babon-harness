"""`manage_worklist` tool, how the assistant carries jobs across days.

Where `remember_note` records a FACT to know later, this records a JOB
to keep working: something to watch, something to look into, or a
question the assistant asked and is waiting on an answer for. It is what lets
The assistant behave like a colleague on shift instead of a thing that only
answers the current message: it can take "keep an eye on the GPU node cost"
and still be on it tomorrow, and it can ask you something and remember it
asked.

One tool, four actions (mirrors `scw_read`'s action shape so the LLM has
one verb, not four):
  - ``add``:      open an item: kind watch | look_into | question.
  - ``progress``: record the latest thing learned on an open item.
  - ``close``:    mark an item done (answered / resolved / dropped).
  - ``list``:     show the current open worklist.

Sanctioned by the house rules: the assistant's own artefact, its own
SQLite, no new IAM surface, same class as `remember_note`. Wired into
the chat loop and the patrol loop, not the shared read-only registry.

Tool-module grammar: ``NAME``, ``DEFINITION``, ``execute``.

FAILURE POLICY: Tier-2 in the calling loop's dispatch (a fault returns as
text to the LLM); the underlying `state.worklist` writes are Tier-1.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from apps.assistant.core import state
from apps.assistant.core.tools.meta.remember_note import unbacked_citation_refusal

NAME = "manage_worklist"

DEFINITION: dict[str, Any] = {
    "name": NAME,
    "description": (
        "Your worklist, the work you carry across days: add what you are asked "
        "or decide to watch or look into, and every question you ask someone; "
        "progress what you learned; close when resolved; list what is open."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "progress", "close", "list"],
            },
            "kind": {
                "type": "string",
                "enum": ["watch", "look_into", "question"],
                "description": (
                    "watch (check each pass), look_into (pursue to an answer), "
                    "question (waiting on a person)."
                ),
            },
            "title": {
                "type": "string",
                "description": "The job in one line.",
            },
            "item_id": {
                "type": "integer",
                "description": "The item id.",
            },
            "text": {
                "type": "string",
                "description": "What you learned, or the resolution.",
            },
        },
        "required": ["action"],
    },
}


def execute(
    tool_input: dict,
    owner: str = "assistant",
    evidence: Callable[[], Sequence[str]] | None = None,
) -> str:
    action = str(tool_input.get("action", "")).strip()
    if action == "add":
        kind = str(tool_input.get("kind", "")).strip()
        title = str(tool_input.get("title", "")).strip()
        if kind not in ("watch", "look_into", "question") or not title:
            return "add needs kind (watch|look_into|question) and a title"
        item_id = state.worklist.add_item(kind, title, owner=owner)
        return f"tracking as worklist item {item_id} ({kind}): {title}"
    if action == "progress":
        item_id = tool_input.get("item_id")
        text = str(tool_input.get("text", "")).strip()
        if not item_id or not text:
            return "progress needs item_id and text"
        unbacked = unbacked_citation_refusal(text, evidence)
        if unbacked:
            return unbacked
        moved = state.worklist.record_progress(int(item_id), text)
        if moved:
            return f"noted progress on item {item_id}"
        return (
            f"item {item_id} is unchanged; recorded that you checked it, and "
            "left the finding alone so the item does not read as news"
        )
    if action == "close":
        item_id = tool_input.get("item_id")
        if not item_id:
            return "close needs item_id"
        resolution = str(tool_input.get("text", "")).strip()
        unbacked = unbacked_citation_refusal(resolution, evidence)
        if unbacked:
            return unbacked
        state.worklist.close_item(int(item_id), resolution)
        return f"closed item {item_id}"
    if action == "list":
        rendered = state.worklist.render()
        return rendered or "worklist is empty"
    return f"unknown action: {action!r} (use add|progress|close|list)"
