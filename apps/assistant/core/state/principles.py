"""`principles` table adapter, the operating principles the owner teaches
openclaw, which every loop applies.

Storage-grammar table adapter (blueprint §2.3): insert, list and delete
live together. These are the learned principles; the baked-in starter set
lives in `core.principles`. When the owner corrects openclaw or teaches it a rule
("stop relaying unit refreshes", "always flag a stuck rotation"), the chat
loop records it here via the `remember_principle` tool, and from then on it
shows up in every loop's prompt.

FAILURE POLICY: Tier-1 fail-loud, a principles read/write error propagates.
A broken principles store must fail loudly, not silently make openclaw forget
what it was taught.
"""
from __future__ import annotations

from typing import Any

from apps.assistant.core.state.conn import get_connection
from apps.assistant.core.state.utcnow_iso import utcnow_iso


def add_principle(text: str, source: str = "owner") -> bool:
    """Record a principle; skip the insert when the identical rule is already
    stored. Returns True if a new row landed, False if it was already there.

    Idempotent because the chat loop re-fires `remember_principle` when a
    confirming question ("did you note that?") is misread as a fresh command;
    a duplicate rule is harmless but clutters every loop's prompt, so collapse
    it here rather than trusting the model not to re-teach."""
    cleaned = text.strip()
    with get_connection() as conn:
        already = conn.execute(
            "SELECT 1 FROM principles WHERE lower(text) = lower(?) LIMIT 1",
            (cleaned,),
        ).fetchone()
        if already:
            return False
        conn.execute(
            "INSERT INTO principles (text, source, added_at) VALUES (?, ?, ?)",
            (cleaned, source, utcnow_iso()),
        )
        conn.commit()
        return True


def list_principles() -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM principles ORDER BY id ASC"
        ).fetchall()
    return [dict(row) for row in rows]


def delete_principle(principle_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM principles WHERE id = ?", (principle_id,))
        conn.commit()
