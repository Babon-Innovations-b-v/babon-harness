"""What the assistant sent from outside the recipient's chat session, for the chat relay.

The gateway answers each person's Signal messages in that person's own chat
session (`session.dmScope` "per-channel-peer"). Everything else the assistant
says to them leaves from somewhere that session never sees: the container's pages,
the pen, patrol, the security sweep, meeting minutes and reminders, the weekday
brief and the advisor, which run in isolated cron sessions and send through
`message_teammate`, and a message somebody else asked the assistant to send them, which
leaves from the asker's session. So a reply lands in a conversation that does
not hold the question it answers, and a "Yes" to the brief's question can be
taken as an answer to a days-old message about something else.

A VM-side timer (`apps/assistant/watch/chat_relay.py`)
reads this feed and copies each send into its recipient's session as the assistant's
own words, so the reply finds its question and the assistant sees how people answered
what it said. Each send carries the number it went to, which is what the
gateway keys that person's session by.

WHAT IS LEFT OUT. A row with no loop predates the relay and is left out,
because its road is unknown. The one duplicate left is a person asking the assistant to
message themselves: that send is already in their session as a tool call and
is relayed back into it once.

A send older than `MAX_AGE_HOURS` is not relayed, whatever the cursor says. A
relay that was down for a week, or a cursor reset to zero, must not empty a
week of pages into one conversation as if they were news.

EACH SEND CARRIES THE WORKLIST ITEMS IT CONCERNS. A reply closes a
question only through `record_answer`, which needs the item's id, and nothing
the chat saw ever carried one, so it was never called. A road
that knows which item it is speaking about stores the ids with the chat turn
(`chat_turns.worklist_items`), and the send carries those still open as
`concerns`. A send with none carries `open_items` instead: the recipient's open
items and the assistant's own, the most recently moved first and at most
`OPEN_ITEMS_SHOWN`, so a long list cannot bury the page. Never both, because a
list beside the one item would make the chat guess again.

FAILURE POLICY: Tier-1. A read that fails raises to the route, which answers
500, and the relay leaves its cursor where it was and tries again. The worklist
read is Tier-2: when it fails the sends go out with no items, because a page the
chat never sees costs more than a page without its ids.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from apps.assistant.core import people
from apps.assistant.core.state import chat_turns, worklist

log = logging.getLogger(__name__)

#: Each road whose sends the recipient's session never saw, and how the note names it.
RELAYED_LOOPS: dict[str, str] = {
    "page": "an alert page",
    "pen": "a batched notification",
    "patrol": "my patrol pass",
    "security": "the security sweep",
    "minutes": "the meeting minutes",
    "meeting-reminder": "a meeting reminder",
    "teammate-self": "a message nobody asked for (the brief, the advisor or my own initiative)",
    "teammate-asked": "a message someone asked me to send",
}

MAX_AGE_HOURS = 24
MAX_LIMIT = 50
OPEN_ITEMS_SHOWN = 5
_ASSISTANT_OWNER = "assistant"


@dataclass(frozen=True)
class Feed:
    """One page of the feed: the newest row id, and the sends past the cursor."""

    newest_id: int
    sends: list[dict[str, object]]


def sends_after(after_id: int, limit: int = 20) -> Feed:
    """The relayable sends past `after_id`, oldest first, each with its recipient's name."""
    since = (datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)).isoformat()
    newest, rows = chat_turns.sent_after(
        max(0, after_id), since, tuple(RELAYED_LOOPS), max(1, min(limit, MAX_LIMIT))
    )
    items = _open_items() if rows else []
    sends = []
    for row in rows:
        person = people.identify_by_number(str(row["sender"]))
        recipient = person.name if person else str(row["sender"])
        sends.append({
            "id": int(row["id"]),
            "sent_at": str(row["created_at"]),
            "loop": str(row["loop"]),
            "road": RELAYED_LOOPS[str(row["loop"])],
            "recipient": recipient,
            "address": str(row["sender"]),
            "text": str(row["text"]),
            **_items_field(row, recipient, items),
        })
    return Feed(newest_id=newest, sends=sends)


def _items_field(
    row: dict[str, object], recipient: str, items: list[dict[str, object]]
) -> dict[str, list[dict[str, object]]]:
    """The send's worklist fields: the open items it concerns, or else the recipient's list."""
    concerns = _concerned(row, items)
    if concerns:
        return {"concerns": concerns, "open_items": []}
    return {"concerns": [], "open_items": _items_for(recipient, items)}


def _concerned(row: dict[str, object], items: list[dict[str, object]]) -> list[dict[str, object]]:
    """The open items whose ids the send's row recorded, in the order it recorded them."""
    by_id = {int(item["id"]): item for item in items}
    recorded = [part.strip() for part in str(row.get("worklist_items") or "").split(",")]
    ids = [int(part) for part in recorded if part.isdigit()]
    return [
        {"id": item_id, "title": str(by_id[item_id]["title"])}
        for item_id in dict.fromkeys(ids)
        if item_id in by_id
    ]


def _open_items() -> list[dict[str, object]]:
    """Every open worklist item, or none when the worklist cannot be read (Tier-2)."""
    try:
        return worklist.open_items()
    except Exception as exc:  # noqa: BLE001 - Tier-2: the sends still go out
        log.warning("could not read the worklist for the relay feed: %s", exc)
        return []


def open_items_for(address: str) -> list[dict[str, object]]:
    """The open items a page to `address` may concern: theirs and the assistant's, capped.

    The same short list a send with no item of its own carries, so triage picks
    a page's item from exactly what the chat would have been shown.
    """
    person = people.identify_by_number(address)
    return _items_for(person.name if person else address, _open_items())


def _items_for(recipient: str, items: list[dict[str, object]]) -> list[dict[str, object]]:
    """The recipient's open items and the assistant's own, most recently moved first, capped."""
    owners = {recipient.strip().lower(), _ASSISTANT_OWNER}
    theirs = [item for item in items if str(item.get("owner", "")).strip().lower() in owners]
    theirs.sort(key=lambda item: (str(item.get("updated_at") or ""), int(item["id"])), reverse=True)
    return [{"id": int(item["id"]), "title": str(item["title"])} for item in theirs[:OPEN_ITEMS_SHOWN]]
