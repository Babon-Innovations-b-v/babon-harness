"""`security_events` table adapter, openclaw's own attack-surface log.

The assistant's public surface is the bearer-gated `alerts.example.org/webhook/*`
and the Signal chat allowlist. Until now a wrong-bearer flood (someone
brute-forcing the shared secret) and a chat attempt from a
non-allowlisted number (someone who found the bot number) were refused
correctly but logged only, zero alert. This table records each such
event so the security sweep can page on a burst.

Storage-grammar adapter (blueprint §2.3): append + windowed count live
together. Append-only; the security sweep reads a recent window.

FAILURE POLICY: Tier-1 fail-loud, a failed write propagates to the
gate (which already fails the request); a security event we could not
record must not be silently lost.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from apps.assistant.core.state.conn import get_connection
from apps.assistant.core.state.utcnow_iso import utcnow_iso

# kind values: 'bad_bearer' (401 on a /webhook/* route), 'unauthorized_chat'
# (allowlist drop on /webhook/signal).


def record_security_event(kind: str, source: str, detail: str = "") -> None:
    """Append one security event (an auth failure or unauthorized access)."""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO security_events (kind, source, detail, created_at) "
            "VALUES (?, ?, ?, ?)",
            (kind, source[:120], detail[:280], utcnow_iso()),
        )
        conn.commit()


def recent_security_events(window_minutes: int = 15) -> list[dict[str, Any]]:
    """Every security event in the trailing window, oldest-first."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    ).isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, kind, source, detail, created_at FROM security_events "
            "WHERE created_at >= ? ORDER BY created_at ASC, id ASC",
            (cutoff,),
        ).fetchall()
    return [dict(row) for row in rows]


def count_since(kind: str, window_minutes: int) -> int:
    """How many events of one kind in the trailing window."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    ).isoformat()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM security_events "
            "WHERE kind = ? AND created_at >= ?",
            (kind, cutoff),
        ).fetchone()
    return int(row["n"])
