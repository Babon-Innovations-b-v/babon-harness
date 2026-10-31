"""`record_answer` tool: a teammate's reply closes the question the assistant asked.

The assistant asks in one session and hears the answer in another. The morning brief
and the advisor run as gateway cron sessions and send through
`message_teammate`; the reply arrives in the gateway's main chat session,
which never saw the question and has no road into anything of ours. Without
this tool a reply lands only in a transcript, the worklist row stays open with
nothing on it, and the next brief asks the same question again.

This is that road. The chat session, when a message answers an open item,
calls it with the item, the answer and who gave it, and it does two writes:

  1. the answer on the worklist row (`worklist.record_answer`), so the next
     brief reads it in the worklist block and can use it;
  2. the already-told ledger stamped answered for that reader
     (`reported_items.mark_answered`), so `message_teammate` refuses to put
     the item to them again.

It refuses, with nothing written: an empty answer, an item id that is not a
number, an item that does not exist or is no longer open, and an `answered_by`
the people registry does not hold. The door adds `requested_by` like on every
write, and `record_answer` is NOT one the assistant may book to itself: an answer is a
person's.

It does not post the answer on the GitHub issue. `github_act comment` already
does that behind its kill switch and its own audit row, and folding it in here
would make recording an answer fail whenever the board write is switched off.

It is not a heuristic. Deciding that a message IS an answer is the model's
call, made in the session that read it; what this enforces is that once the
call is made, the answer lands somewhere every other session reads.

Tool-module grammar: NAME, DEFINITION, execute.

FAILURE POLICY: refusals return as text in `write_guard.refuse`'s shape, so
the door marks them failed; both state writes are Tier-1 and propagate.
"""
from __future__ import annotations

from typing import Any

from apps.assistant.core import people, state
from apps.assistant.core.tools import write_guard

NAME = "record_answer"

DEFINITION: dict[str, Any] = {
    "name": NAME,
    "description": (
        "Record a teammate's answer to an open worklist item when a message here "
        "answers it. Call it before you reply, so the question is not asked "
        "again."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "item_id": {
                "type": "integer",
                "description": "The open worklist item.",
            },
            "answer": {
                "type": "string",
                "description": "Their answer, short.",
            },
            "answered_by": {
                "type": "string",
                "description": "Who answered.",
            },
        },
        "required": ["item_id", "answer", "answered_by"],
    },
}


def execute(tool_input: dict[str, Any], actor: str = "assistant") -> str:
    """Record one answer on one open item, or refuse with nothing written."""
    answer = str(tool_input.get("answer") or "").strip()
    if not answer:
        return write_guard.refuse("the answer is empty, so there is nothing to record.")
    try:
        item_id = int(tool_input.get("item_id"))
    except (TypeError, ValueError):
        return write_guard.refuse("item_id must be the worklist item's number.")
    answered_by = _registry_name(str(tool_input.get("answered_by") or ""))
    if answered_by is None:
        return write_guard.refuse(
            f"my people registry holds nobody called "
            f"{tool_input.get('answered_by')!r}; name who answered as the "
            "registry spells them."
        )
    row = state.worklist.item(item_id)
    if row is None:
        return write_guard.refuse(f"there is no worklist item {item_id}.")
    if str(row.get("status")) != "open":
        return write_guard.refuse(
            f"worklist item {item_id} is already closed, so it is not waiting "
            "on an answer."
        )
    state.worklist.record_answer(item_id, answer, answered_by)
    state.reported_items.mark_answered(
        state.reported_items.reader_key(item_id, str(row.get("owner", "")), answered_by)
    )
    return f"recorded answer on item {item_id} from {answered_by}: {answer[:120]}"


def _registry_name(claimed: str) -> str | None:
    """The registry's own spelling of `claimed`, or None (case-insensitive)."""
    wanted = claimed.strip().lower()
    if not wanted:
        return None
    return next((name for name in people.names() if name.lower() == wanted), None)
