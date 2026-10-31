"""Read the single-row sync-status payload."""
from __future__ import annotations

from dashkit.core.sync.table import (
    ensure_sync_status_table,
)


def fetch_sync_status(conn, table_name: str) -> dict:
    """Return the single-row ``{table_name}`` payload as a dict."""
    ensure_sync_status_table(conn, table_name)
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT last_run_at, last_run_status, last_run_duration_ms, "
            f"last_run_error FROM {table_name} WHERE id = 1"
        )
        row = cur.fetchone()
    if not row or row[0] is None:
        return {"status": "stale", "last_run_at": None}
    return {
        "status": row[1] or "unknown",
        "last_run_at": row[0].isoformat() if row[0] else None,
        "last_run_duration_ms": row[2],
        "last_run_error": row[3],
    }
