"""Mutes still standing on a card that has been closed.

When a subject keeps coming back, the assistant files one card for it and the notify
pen stops paging about it (`state.filed_observations`, read by
`notify_flush._split_silenced`). The mute runs ninety days, and closing the
card does not lift it, on purpose: most of those cards are closed as done,
and lifting their mutes would bring the noise back. What must not happen is the other half, a ping silenced by a card nobody
is looking at any more, so a closed card's mute is reported instead of lifted.

This module answers that report: for every filed card GitHub says is CLOSED,
one line naming the card, the subject it still mutes and until when, and how
many pings it silenced since `since` with the newest one's local time. A
ping counts as silenced by a card when its mute key matches the card's and it
arrived while the card's mute was live, which is the same test `_split_silenced`
applied when it cleared it.

It changes nothing: no mute is lifted and no ping is re-sent. The read is
`my_actions`, so the weekday brief and the chat both see it.

Public callable: `report(since)`.

FAILURE POLICY: Tier-1. A state or GitHub fault propagates; the door tool that
calls this turns it into the line saying it could not be read, so an unread
card is never reported as open.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from apps.assistant.core import quiet_hours, state
from apps.assistant.core.ping_facts import mute_key
from apps.assistant.core.tools.gh import issue_states

_CLOSED = "CLOSED"


def report(since: datetime) -> list[str]:
    """One line per closed card whose mute still stands or silenced a ping
    since `since`, newest card first. Empty when there is none, and then
    GitHub is not asked anything."""
    filed = state.list_filed(include_expired=True)
    if not filed:
        return []
    now = datetime.now(timezone.utc).isoformat()
    muted = _muted_by_card(filed, state.pings_flushed_since(since.astimezone(timezone.utc).isoformat()))
    live = {int(row["issue_number"]): row for row in filed if row["expires_at"] > now}
    cards = set(live) | set(muted)
    if not cards:
        return []
    closed = {
        number for number, card_state in issue_states.states(cards).items()
        if card_state == _CLOSED
    }
    by_number = {int(row["issue_number"]): row for row in reversed(filed)}
    return [
        _line(number, live.get(number) or by_number[number], muted.get(number, []), now)
        for number in sorted(closed, reverse=True)
    ]


def _muted_by_card(
    filed: list[dict[str, Any]], pings: list[dict[str, Any]]
) -> dict[int, list[dict[str, Any]]]:
    """The cleared pings each card held, oldest first, keyed by issue number."""
    muted: dict[int, list[dict[str, Any]]] = {}
    for ping in pings:
        key = mute_key(ping["subject"])
        for row in filed:
            if mute_key(row["subject"]) == key and row["filed_at"] <= ping["received_at"] < row["expires_at"]:
                muted.setdefault(int(row["issue_number"]), []).append(ping)
                break
    return muted


def _line(number: int, card: dict[str, Any], pings: list[dict[str, Any]], now: str) -> str:
    """`#N` closed, what it mutes and until when, and what it held back."""
    mutes = "still mutes" if card["expires_at"] > now else "muted"
    line = f"#{number} is closed and {mutes} '{card['subject']}' until {card['expires_at'][:10]}"
    if not pings:
        return line + "; nothing silenced since the last brief."
    return (
        f"{line}; it silenced {len(pings)} ping(s) since the last brief, "
        f"the last at {_local_clock(pings[-1]['received_at'])}."
    )


def _local_clock(moment: str) -> str:
    """A stored UTC timestamp on the reader's clock."""
    parsed = datetime.fromisoformat(moment)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return quiet_hours.local_moment(parsed).strftime("%a %H:%M local")
