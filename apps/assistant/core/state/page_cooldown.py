"""`page_cooldown` table, a persisted "have I already paged this?" gate
for PROACTIVE pages.

The problem it fixes: a proactive page path (security bursts, and
anything future) that tracks "already paged" in memory loses that state on a
pod restart, and the same condition pages again. AM alerts already dedup
through the persisted `dedup_window`; this is the same idea for pages
that aren't AM-driven, but keyed by a caller-chosen fingerprint with a
caller-chosen cooldown, and it SURVIVES RESTARTS because it lives in
SQLite, not RAM. A page decision no longer depends on which timer ticked
or whether the container just restarted.

Single public callable: `should_page(key, cooldown_seconds) -> bool`:
True (and records now) iff `key` has NOT been paged within the cooldown.

FAILURE POLICY: Tier-1 fail-loud like every state adapter. A failed
gate read/write propagates rather than silently double-paging or
silently suppressing.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from apps.assistant.core.state.conn import get_connection
from apps.assistant.core.state.utcnow_iso import utcnow_iso


def should_page(key: str, cooldown_seconds: int) -> bool:
    """True iff `key` was NOT paged within the last `cooldown_seconds`.

    On True, stamps `key` as paged-now (so the next call within the
    cooldown returns False). Restart-safe: the stamp is in SQLite. Use one
    stable key per recurring concern (e.g. 'bad_bearer_burst'), so a burst
    pages once per cooldown no matter how many timer ticks or restarts
    happen inside it."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(seconds=cooldown_seconds)
    ).isoformat()
    now = utcnow_iso()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT last_paged_at FROM page_cooldown WHERE key = ?", (key,)
        ).fetchone()
        if row is not None and row["last_paged_at"] >= cutoff:
            return False  # inside the cooldown, suppress
        conn.execute(
            "INSERT INTO page_cooldown (key, last_paged_at) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET last_paged_at = excluded.last_paged_at",
            (key, now),
        )
        conn.commit()
    return True


def clear(key: str) -> None:
    """Forget a key's last-paged stamp (so the next `should_page` fires).
    Use when a condition has fully cleared and you want the next occurrence
    to page immediately rather than wait out the cooldown."""
    with get_connection() as conn:
        conn.execute("DELETE FROM page_cooldown WHERE key = ?", (key,))
        conn.commit()
