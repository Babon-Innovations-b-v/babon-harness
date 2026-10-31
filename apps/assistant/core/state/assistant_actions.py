"""`assistant_actions` table, the audit trail of everything the assistant DOES, not
just says.

Once the assistant can write to GitHub on its own initiative (comment, create,
assign, label, move board status, close/reopen), every such action is
recorded here BEFORE it is reported, so there is always a durable,
reviewable log of what the assistant changed, the accountability that
makes "full initiative" safe. A wrong action on GitHub is reversible
(reopen, re-open, re-assign); this table is how you find it.

Storage-grammar adapter (blueprint §2.3): the read + write callables live
together here. Append-only.

FAILURE POLICY: Tier-1 fail-loud like every state adapter, the audit
write happens BEFORE the GitHub mutation is reported as done, and its
failure propagates. An action the assistant cannot record is an action it must
not silently take.
"""
from __future__ import annotations

from typing import Any

from apps.assistant.core.state.conn import get_connection
from apps.assistant.core.state.utcnow_iso import utcnow_iso


def record_action(
    kind: str, target: str, summary: str, actor: str = "assistant", detail: str = ""
) -> int:
    """Log one action the assistant took. `kind` e.g. 'gh_comment' / 'gh_create' /
    'gh_close'; `target` e.g. '#42'; `actor` who drove it (assistant on
    its own, or a person who asked). Returns the row id."""
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO assistant_actions (kind, target, summary, actor, detail, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (kind, target[:120], summary[:500], actor[:60], detail[:500], utcnow_iso()),
        )
        conn.commit()
        return int(cur.lastrowid)


def recent_actions(limit: int = 25) -> list[dict[str, Any]]:
    """The most recent actions, newest first, for the morning brief and review."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, kind, target, summary, actor, detail, created_at "
            "FROM assistant_actions ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def actions_since(iso_cutoff: str) -> list[dict[str, Any]]:
    """Actions on or after an ISO timestamp, oldest-first (a day's worth for
    the morning brief)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, kind, target, summary, actor, created_at FROM assistant_actions "
            "WHERE created_at >= ? ORDER BY id ASC",
            (iso_cutoff,),
        ).fetchall()
    return [dict(row) for row in rows]
