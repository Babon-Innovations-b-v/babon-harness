"""`journal` table adapter, openclaw's durable notes-to-self.

Storage-grammar table adapter (blueprint §2.3): insert, windowed read,
range read and delete live together. The journal is what openclaw KNOWS
(findings, events, per-person facts: "disk on node-1 trending up",
"the owner op vakantie t/m vrijdag"); the `principles` table is
how it WORKS. The chat loop writes here via the `remember_note` tool
(openclaw's own artefact, its own SQLite, no new IAM surface);
`core.journal.render()` reads it into every loop's prompt; the weekly
compact reads a week's range to summarise.

FAILURE POLICY: Tier-1 fail-loud, a journal read/write error propagates.
A broken journal must fail loudly, not silently make openclaw forget what
it wrote down.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from apps.assistant.core.state.conn import get_connection
from apps.assistant.core.state.utcnow_iso import utcnow_iso

# Raw notes stay in the prompt for two weeks; the weekly compact carries
# older knowledge forward as summaries, so the window overlaps one compact.
_NOTE_WINDOW_DAYS = 14
_MAX_NOTES = 40


def add_note(text: str, person: str | None = None, source: str = "openclaw") -> None:
    """Append one journal note. `person` tags a note that is about a
    specific teammate (E.164 or name) rather than the system."""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO journal (text, person, source, added_at) "
            "VALUES (?, ?, ?, ?)",
            (text.strip(), person, source, utcnow_iso()),
        )
        conn.commit()


def recent_notes(
    window_days: int = _NOTE_WINDOW_DAYS,
    max_notes: int = _MAX_NOTES,
) -> list[dict[str, Any]]:
    """The newest notes inside the window, oldest-first, bounded by BOTH
    the day window and a note cap (same double bound as chat turns)."""
    cutoff_iso = (
        datetime.now(timezone.utc) - timedelta(days=window_days)
    ).isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, text, person, source, added_at FROM journal "
            "WHERE added_at >= ? ORDER BY added_at DESC, id DESC LIMIT ?",
            (cutoff_iso, max_notes),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def all_notes(max_notes: int = 5000) -> list[dict[str, Any]]:
    """Every journal note, newest-first, bounded only by a high safety cap:
    the knowledge index's read (so the assistant can search its own memory, not just
    the recent window). Distinct from `recent_notes`, which is the prompt's
    small windowed view."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, text, person, source, added_at FROM journal "
            "ORDER BY added_at DESC, id DESC LIMIT ?",
            (max_notes,),
        ).fetchall()
    return [dict(row) for row in rows]


def notes_between(start_iso: str, end_iso: str) -> list[dict[str, Any]]:
    """All notes with `start_iso <= added_at < end_iso`, oldest-first:
    the weekly compact's read."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, text, person, source, added_at FROM journal "
            "WHERE added_at >= ? AND added_at < ? ORDER BY added_at ASC, id ASC",
            (start_iso, end_iso),
        ).fetchall()
    return [dict(row) for row in rows]


def delete_note(note_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM journal WHERE id = ?", (note_id,))
        conn.commit()
