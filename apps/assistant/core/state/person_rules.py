"""`person_rules` table adapter, each teammate's own tone + rules.

Separate from the global `principles` (the owner's system doctrine, applied in
EVERY loop): a person rule applies ONLY when the assistant is talking to that
person, and the person themselves sets it, so a teammate can shape how the assistant
talks to a teammate without touching anyone else's experience or the global
doctrine. Keyed by person name, matched case-insensitively.

Storage-grammar table adapter (blueprint §2.3): insert, list and a
person-scoped delete live together.

FAILURE POLICY: Tier-1 fail-loud, a personal-rules read/write error
propagates, like every state adapter.
"""
from __future__ import annotations

from typing import Any

from apps.assistant.core.state.conn import get_connection
from apps.assistant.core.state.utcnow_iso import utcnow_iso


def add_person_rule(person: str, text: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO person_rules (person, text, added_at) VALUES (?, ?, ?)",
            (person.strip().lower(), text.strip(), utcnow_iso()),
        )
        conn.commit()


def list_person_rules(person: str) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM person_rules WHERE person = ? ORDER BY id ASC",
            (person.strip().lower(),),
        ).fetchall()
    return [dict(row) for row in rows]


def delete_person_rule(rule_id: int, person: str) -> bool:
    """Delete one of THIS person's rules. Scoped to `person` so nobody can
    remove a teammate's rule by guessing an id. Returns True if a row went."""
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM person_rules WHERE id = ? AND person = ?",
            (rule_id, person.strip().lower()),
        )
        conn.commit()
        return cursor.rowcount > 0
