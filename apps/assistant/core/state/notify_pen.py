"""`notify_pen` table adapter, the holding pen for system pings
(collect-think-summarize).

Storage-grammar table adapter (blueprint §2.3): enqueue, unflushed read
and flush-mark live together. The notify gate no longer pages per ping;
it drops every ping in this pen, and the in-container flusher periodically
turns the accumulated batch into ONE summarised message (or silence).
A crash-looping unit that fires OnFailure every 30 seconds becomes one
evolving story instead of a page per failure (collect the alerts,
think about them, send summaries).

`facts` is the sender's own typed marking on its ping, stored as
a JSON object and NULL for every sender that marks nothing, which is
most of them. This table stores
it and does not read it: what a marking MEANS, and which of its keys
anything is allowed to say, is `core.ping_facts`.

FAILURE POLICY: Tier-1 fail-loud on the write, Tier-2 on reading one
marking back. A failed enqueue 500s the gate POST so the caller's
direct-send fallback fires; a ping is never silently dropped into a
broken pen. A row whose `facts` blob will not parse comes back with no
marking rather than taking the batch down with it: the ping is the
thing that has to survive, and the batch it is in carries other pings
whose senders did nothing wrong.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from apps.assistant.core.state.conn import get_connection
from apps.assistant.core.state.utcnow_iso import utcnow_iso

log = logging.getLogger("openclaw.state.notify_pen")


def enqueue_ping(
    subject: str, body: str, source: str, facts: dict[str, Any] | None = None
) -> None:
    """Drop one inbound system ping, and whatever its sender marked, in the pen.

    `facts` defaults to None because most senders mark nothing and every
    caller written before they could still calls this with three arguments.
    """
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO notify_pen (subject, body, source, received_at, facts) "
            "VALUES (?, ?, ?, ?, ?)",
            (subject, body, source, utcnow_iso(), _stored(facts)),
        )
        conn.commit()


def _stored(facts: dict[str, Any] | None) -> str | None:
    """One marking as the column holds it: JSON text, or NULL for no marking.

    A marking that will not serialise is stored as no marking at all, with a
    log line naming the sender's problem. The alternative is raising inside a
    Tier-1 write, which turns a sender's bad enrichment into a lost page.
    """
    if not facts:
        return None
    try:
        return json.dumps(facts)
    except (TypeError, ValueError) as exc:  # a sender marked something unserialisable
        log.warning("dropping unserialisable ping facts: %s", exc)
        return None


def _marking(raw: Any) -> dict[str, Any] | None:
    """One stored marking read back, or None when the row has none it can use.

    NULL (the sender marked nothing, or the row predates markings), text that
    is not JSON, and JSON that is not an object all answer the same way. See
    the failure policy: a marking is never worth a batch.
    """
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError) as exc:
        log.warning("unreadable ping facts in the pen: %s", exc)
        return None
    return parsed if isinstance(parsed, dict) and parsed else None


def unflushed_pings() -> list[dict[str, Any]]:
    """Every ping not yet folded into a flush, oldest-first.

    `facts` comes back decoded, so no reader has to know the column is text.
    """
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, subject, body, source, received_at, facts FROM notify_pen "
            "WHERE flushed_at IS NULL ORDER BY received_at ASC, id ASC"
        ).fetchall()
    pings = []
    for row in rows:
        ping = dict(row)
        ping["facts"] = _marking(ping.get("facts"))
        pings.append(ping)
    return pings


def flushed_since(since_iso: str, limit: int = 500) -> list[dict[str, Any]]:
    """Pings received at or after `since_iso` that a flush has cleared, oldest
    first, as (id, subject, received_at, flushed_at). Bounded: the morning
    brief reads it to find what a filed card muted overnight."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, subject, received_at, flushed_at FROM notify_pen "
            "WHERE flushed_at IS NOT NULL AND received_at >= ? "
            "ORDER BY received_at ASC, id ASC LIMIT ?",
            (since_iso, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def pending_count() -> int:
    """How many pings are still waiting in the pen right now.

    A COUNT rather than `len(unflushed_pings())`, because the caller is the
    weekly silence report and it wants a number, not a night of ping bodies.

    THIS IS THE NUMBER THAT KEEPS THE SILENCE COUNT HONEST. A ping still in the
    pen has not been judged and nobody has been told about it, so it looks
    exactly like a silence from the `alerts` table, which holds nothing about
    it: the pen's quiet-hours hold and its story-gap hold both write no row at
    all. It is not a silence. It is the brake working, and on a busy night that brake is the largest
    single reason a person's phone stays quiet, which is what it is for.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS waiting FROM notify_pen WHERE flushed_at IS NULL"
        ).fetchone()
    return int(row["waiting"] or 0) if row else 0


def mark_flushed(ping_ids: list[int]) -> None:
    """Stamp the given pings as handled by one flush.

    Handled, not said. A batch that was judged noise and a batch whose subject
    is already on the board are both cleared through here, and neither of them
    reached a phone, so nothing may read this stamp as evidence that the pen
    spoke. What the pen last SENT is `alerts.last_pen_page_at`.
    """
    if not ping_ids:
        return
    now = utcnow_iso()
    with get_connection() as conn:
        conn.executemany(
            "UPDATE notify_pen SET flushed_at = ? WHERE id = ?",
            [(now, ping_id) for ping_id in ping_ids],
        )
        conn.commit()


def last_flush_at() -> str | None:
    """When the pen last cleared a ping, None if it never has.

    This was the flusher's pacing input at first and is not one any
    more: MAX(flushed_at) counts silences, so a batch that sent nothing opened
    a full story gap in front of the next real page. Pacing reads
    `alerts.last_pen_page_at` now. What is left here is the pen table's own
    honest read-back, which a state round-trip check can use to prove an
    enqueued ping can be cleared at all.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT MAX(flushed_at) AS latest FROM notify_pen"
        ).fetchone()
    return row["latest"]
