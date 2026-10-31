"""`meeting_reminders` table, a persisted "have I already reminded this
person about this meeting?" gate (slice 1).

The 15-min-before reminder runs on a VM timer every few minutes and scans
a wide window, so the same upcoming meeting is seen on several ticks (and
again after a pod restart). This gate makes each reminder fire EXACTLY
ONCE per recipient per meeting occurrence: the beat claims a key before
sending, and a claim already taken means "already reminded, skip". It
lives in SQLite, so a pod restart cannot make the assistant re-remind a meeting it
already reminded.

Two public callables: `claim(reminder_key) -> bool` (True and records iff
the key is new) and `vacuum_old(days)` (drop stale rows so the table does
not grow without bound).

FAILURE POLICY: Tier-1 fail-loud like every state adapter, a failed
read/write propagates rather than silently re-reminding or silently
dropping a reminder.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from apps.assistant.core.state.conn import get_connection
from apps.assistant.core.state.utcnow_iso import utcnow_iso


def claim(reminder_key: str) -> bool:
    """True (and records `reminder_key` as reminded-now) iff it has not been
    claimed before; False if it is already recorded. Use one stable key per
    (recipient, meeting occurrence), e.g. '<number>|<call link>|<start>', so a
    meeting reminds a person once no matter how many ticks or restarts see
    it in the window."""
    now = utcnow_iso()
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO meeting_reminders (reminder_key, reminded_at) "
            "VALUES (?, ?)",
            (reminder_key, now),
        )
        conn.commit()
        return cursor.rowcount > 0


def vacuum_old(days: int = 2) -> None:
    """Drop reminder rows older than `days`, a meeting past is never
    reminded again, so its row is dead weight. Keeps the table from growing
    without bound."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with get_connection() as conn:
        conn.execute("DELETE FROM meeting_reminders WHERE reminded_at < ?", (cutoff,))
        conn.commit()
