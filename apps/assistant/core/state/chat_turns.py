"""`chat_turns` table adapter, per-sender Signal chat history
with a week of memory.

Storage-grammar table adapter (blueprint §2.3): append and windowed
read live together. Append-only; trimming happens at read time via the
window + turn-cap + char-cap in `recent_chat_turns`. Outbound pages and
digests are also appended here (role `assistant`, via `core.outbound`),
so the history holds everything openclaw said to a person, not only its
chat replies. Since the gateway took the chat nothing replays
this into a conversation; `recent_sent_turns` is what `my_actions` shows.

FAILURE POLICY: Tier-1 fail-loud, chat-turn read/write errors
propagate to `core.chat`, which surfaces a terse error reply instead
of silently dropping conversation state.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from apps.assistant.core.state.conn import get_connection
from apps.assistant.core.state.utcnow_iso import utcnow_iso

# A week of raw memory (the weekly compact carries anything older). The turn cap and char cap bound
# what one prompt can grow to; the caps trim oldest-first.
_CHAT_WINDOW_SECONDS = 7 * 24 * 3600
_CHAT_MAX_TURNS = 40
_CHAT_MAX_CHARS = 24_000


def append_chat_turn(
    sender: str,
    role: str,
    text: str,
    loop: str | None = None,
    worklist_items: tuple[int, ...] = (),
) -> None:
    """Append one chat turn (a user message or an assistant answer) for a
    given Signal sender. `loop` names the road a sent message left by; the
    chat relay reads it and NULL means nobody said. `worklist_items`
    are the ids of the worklist items a sent message is about, stored
    comma-joined and NULL when the road knew of none."""
    items = ",".join(str(int(item_id)) for item_id in worklist_items) or None
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO chat_turns (sender, role, text, created_at, loop, worklist_items) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sender, role, text, utcnow_iso(), loop, items),
        )
        conn.commit()


def recent_chat_turns(
    sender: str,
    window_seconds: int = _CHAT_WINDOW_SECONDS,
    max_turns: int = _CHAT_MAX_TURNS,
    max_chars: int = _CHAT_MAX_CHARS,
) -> list[dict[str, Any]]:
    """Return this sender's recent chat turns, oldest-first, bounded by
    a time window, a turn cap AND a total-character cap.

    The SQL pulls the newest `max_turns` rows inside the window (newest-
    first via `created_at DESC LIMIT`); we then keep newest turns until
    the char budget is spent (always at least the newest turn) and
    reverse to oldest-first so the caller can prepend them as
    conversation history in order.
    """
    cutoff_iso = (
        datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
    ).isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT sender, role, text, created_at FROM chat_turns "
            "WHERE sender = ? AND created_at >= ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (sender, cutoff_iso, max_turns),
        ).fetchall()
    kept: list[dict[str, Any]] = []
    budget = max_chars
    for row in rows:  # newest-first
        budget -= len(row["text"])
        if budget < 0 and kept:
            break
        kept.append(dict(row))
    return list(reversed(kept))


def recent_sent_turns(limit: int) -> list[dict[str, Any]]:
    """The newest `limit` messages the assistant sent anyone, newest-first.

    Every road out of the container appends here after a successful send
    (`message_teammate`, the meeting reminder, `core.outbound.remember_sent`
    for pages, the pen, patrol and the morning line). The gateway's chat
    session cannot see any of them, so `my_actions` reads this to show it
    what it said from somewhere else.
    """
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT sender, role, text, created_at FROM chat_turns "
            "WHERE role = 'assistant' "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def sent_after(
    after_id: int, since_iso: str, loops: tuple[str, ...], limit: int
) -> tuple[int, list[dict[str, Any]]]:
    """The newest row id, and up to `limit` sent rows past `after_id`, oldest first.

    Only `assistant` rows whose `loop` is one of `loops` and that are no older
    than `since_iso`. The id is read in the same connection as the rows and the
    rows are bounded by it, so a reader that advances to it never skips a row
    written between the two reads.
    """
    marks = ",".join("?" for _ in loops) or "NULL"
    with get_connection() as conn:
        newest = conn.execute("SELECT COALESCE(MAX(id), 0) FROM chat_turns").fetchone()[0]
        rows = conn.execute(
            "SELECT id, sender, text, created_at, loop, worklist_items FROM chat_turns "
            f"WHERE role = 'assistant' AND id > ? AND id <= ? AND created_at >= ? "
            f"AND loop IN ({marks}) ORDER BY id ASC LIMIT ?",
            (after_id, newest, since_iso, *loops, limit),
        ).fetchall()
    return int(newest), [dict(row) for row in rows]


def sent_to_since(sender: str, loop: str, since_iso: str) -> list[dict[str, Any]]:
    """Messages delivered to `sender` on road `loop` at or after `since_iso`,
    oldest first. `page_hold` reads it to see whether the morning brief has
    landed and what it said."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT text, created_at FROM chat_turns "
            "WHERE role = 'assistant' AND sender = ? AND loop = ? AND created_at >= ? "
            "ORDER BY created_at ASC, id ASC",
            (sender, loop, since_iso),
        ).fetchall()
    return [dict(row) for row in rows]


def turns_between(start_iso: str, end_iso: str) -> list[dict[str, Any]]:
    """All turns of ALL senders with `start_iso <= created_at < end_iso`,
    oldest-first, the weekly compact's read."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT sender, role, text, created_at FROM chat_turns "
            "WHERE created_at >= ? AND created_at < ? "
            "ORDER BY created_at ASC, id ASC",
            (start_iso, end_iso),
        ).fetchall()
    return [dict(row) for row in rows]
