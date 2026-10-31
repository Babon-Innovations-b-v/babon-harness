"""`weekly_compacts` table adapter, openclaw's long-term memory.

Storage-grammar table adapter (blueprint §2.3): insert and reads live
together. Once a week `core.compact` summarises the past week (raw chat
turns + journal notes + the commits and issues GitHub holds for it) into
ONE text row here; these rows
are what openclaw still knows after the raw two-week windows roll off.
`core.journal.render()` injects the newest few into every loop's prompt.

FAILURE POLICY: Tier-1 fail-loud, a compact read/write error propagates.
Losing a week's memory silently is exactly the failure this table exists
to prevent.
"""
from __future__ import annotations

from typing import Any

from apps.assistant.core.state.conn import get_connection
from apps.assistant.core.state.utcnow_iso import utcnow_iso

_MAX_COMPACTS_IN_PROMPT = 8


def add_compact(week_start: str, week_end: str, text: str) -> None:
    """Store one week's summary. `week_start`/`week_end` are ISO
    timestamps bounding the summarised window (end-exclusive)."""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO weekly_compacts (week_start, week_end, text, created_at) "
            "VALUES (?, ?, ?, ?)",
            (week_start, week_end, text.strip(), utcnow_iso()),
        )
        conn.commit()


def list_compacts(max_compacts: int = _MAX_COMPACTS_IN_PROMPT) -> list[dict[str, Any]]:
    """The newest compacts, oldest-first (prompt order)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, week_start, week_end, text, created_at "
            "FROM weekly_compacts ORDER BY week_end DESC, id DESC LIMIT ?",
            (max_compacts,),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def all_compacts(max_compacts: int = 500) -> list[dict[str, Any]]:
    """Every weekly compact, newest-first, bounded only by a high safety cap:
    the knowledge index's read (distinct from `list_compacts`, the prompt's
    small view)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, week_start, week_end, text, created_at "
            "FROM weekly_compacts ORDER BY week_end DESC, id DESC LIMIT ?",
            (max_compacts,),
        ).fetchall()
    return [dict(row) for row in rows]


def latest_week_end() -> str | None:
    """The end bound of the newest compact, or None if none exist, the
    compact job starts its next window here so weeks never double-compact."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT week_end FROM weekly_compacts ORDER BY week_end DESC LIMIT 1"
        ).fetchone()
    return row["week_end"] if row else None
