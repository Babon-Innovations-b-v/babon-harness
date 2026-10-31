"""Read recent activity-log rows, newest first."""
from __future__ import annotations

from typing import Any

from dashkit.core.audit.table import (
    ensure_activity_table,
)


def fetch_activity(
    conn,
    table_name: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return up to ``limit`` rows from ``{table_name}`` newest-first.

    Caller owns the connection (does not close). Propagates DB errors:
    a broken audit surface should 500/503 in the dashboard, not render
    an empty timeline.
    """
    ensure_activity_table(conn, table_name)
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT id, action_type, user_name, doc_path, section_id, "
            f"detail, created_at FROM {table_name} "
            f"ORDER BY created_at DESC LIMIT %s",
            (min(max(limit, 1), 500),),
        )
        return [
            {
                "id": row[0],
                "type": row[1],
                "action_type": row[1],
                "user": row[2],
                "path": row[3],
                "doc_path": row[3],
                "section_id": row[4],
                "detail": row[5],
                "timestamp": row[6].isoformat() if row[6] else None,
            }
            for row in cur.fetchall()
        ]
