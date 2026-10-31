"""`dedup_window` table adapter, 5-min sliding window keyed by
alert fingerprint.

Storage-grammar table adapter (blueprint §2.3): the window check-and-
touch and its housekeeping vacuum live together. The window length is
declared once here.

FAILURE POLICY: Tier-1 fail-loud, dedup read/write errors propagate.
A broken dedup store must fail the webhook (Alertmanager retries)
rather than risk double-paging or silently dropping alerts.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from apps.assistant.core.state.conn import get_connection
from apps.assistant.core.state.utcnow_iso import utcnow_iso

_DEDUP_WINDOW_SECONDS = 300  # 5 minutes


def dedup_check_and_touch(fingerprint: str) -> bool:
    """Return True if this fingerprint was seen within the dedup window.
    Always upserts the seen-row, so a returning True means we already
    triaged this event recently.
    """
    now_iso = utcnow_iso()
    cutoff_iso = (
        datetime.now(timezone.utc) - timedelta(seconds=_DEDUP_WINDOW_SECONDS)
    ).isoformat()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT last_seen_at, count FROM dedup_window WHERE fingerprint = ?",
            (fingerprint,),
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO dedup_window (fingerprint, first_seen_at, last_seen_at, count) "
                "VALUES (?, ?, ?, 1)",
                (fingerprint, now_iso, now_iso),
            )
            conn.commit()
            return False
        is_dup = row["last_seen_at"] >= cutoff_iso
        conn.execute(
            "UPDATE dedup_window SET last_seen_at = ?, count = count + 1 "
            "WHERE fingerprint = ?",
            (now_iso, fingerprint),
        )
        conn.commit()
        return is_dup


def vacuum_old_dedup_rows() -> int:
    """Drop dedup_window rows whose last_seen_at is older than the
    dedup horizon. Cheap housekeeping; runs on demand. Returns the
    number of rows removed.
    """
    cutoff = (
        datetime.now(timezone.utc) - timedelta(seconds=_DEDUP_WINDOW_SECONDS * 6)
    ).isoformat()
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM dedup_window WHERE last_seen_at < ?",
            (cutoff,),
        )
        conn.commit()
        return cursor.rowcount or 0
