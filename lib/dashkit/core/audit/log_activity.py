"""Insert one activity-log row (best-effort)."""
from __future__ import annotations

import json
import logging
from typing import Optional

from dashkit.core.audit.table import (
    ensure_activity_table,
)

logger = logging.getLogger("dashkit.audit")


def log_activity(
    conn,
    table_name: str,
    action_type: str,
    user: str,
    doc_path: Optional[str] = None,
    section_id: Optional[str] = None,
    detail: Optional[dict] = None,
) -> None:
    """Insert one row into ``{table_name}``.

    CALLER MUST commit(): this helper deliberately runs inside the
    caller's transaction so the activity row and the mutation
    succeed-or-fail atomically. Do NOT add ``conn.commit()`` here.

    FAILURE POLICY: best-effort swallow. An audit-log failure must never
    break the actual feature; observability fails open. Logged at
    WARNING so the gap is still visible in the journal.
    """
    try:
        ensure_activity_table(conn, table_name)
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {table_name} "
                f"(action_type, user_name, doc_path, section_id, detail) "
                f"VALUES (%s, %s, %s, %s, %s)",
                (
                    action_type,
                    user or "anonymous",
                    doc_path,
                    section_id,
                    json.dumps(detail) if detail else None,
                ),
            )
    except Exception as exc:
        logger.warning("log_activity(%s) failed (swallowed): %s", table_name, exc)
