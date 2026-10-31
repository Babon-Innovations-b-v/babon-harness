"""Lazy single-row ``{domain}_sync_status`` bootstrap shared by the sync read/write seams."""
from __future__ import annotations

import logging

from dashkit.core.identifiers import validate_table_name

logger = logging.getLogger("dashkit.sync")

_table_ready: dict[str, bool] = {}


def ensure_sync_status_table(conn, table_name: str) -> None:
    """Lazily create ``{table_name}`` (single-row table) on first use.

    Best-effort swallow: bootstrap failure is logged, not raised. The read
    path returns ``{"status": "stale"}`` for a missing row and the
    write path will surface its own error on the UPDATE.
    """
    validate_table_name(table_name)
    if _table_ready.get(table_name):
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    id                   INTEGER PRIMARY KEY DEFAULT 1,
                    last_run_at          TIMESTAMPTZ,
                    last_run_status      TEXT,
                    last_run_duration_ms INTEGER,
                    last_run_error       TEXT,
                    CHECK (id = 1)
                )
                """
            )
            cur.execute(
                f"INSERT INTO {table_name} (id) VALUES (1) "
                f"ON CONFLICT DO NOTHING"
            )
        conn.commit()
        _table_ready[table_name] = True
    except Exception as exc:
        logger.warning("ensure_sync_status_table(%s) failed: %s", table_name, exc)
        try:
            conn.rollback()
        except Exception:
            logger.warning("rollback after failed sync-table bootstrap also failed")
