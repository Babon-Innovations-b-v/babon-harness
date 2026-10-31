"""Lazy ``{domain}_activity`` table bootstrap shared by the audit read/write seams."""
from __future__ import annotations

from dashkit.core.identifiers import validate_table_name

# Per-table "already created?" flags so the lazy CREATE TABLE only runs
# once per process per table. Keyed by table name.
_table_ready: dict[str, bool] = {}


def ensure_activity_table(conn, table_name: str) -> None:
    """Lazily create ``{table_name}`` on first use. Safe to call repeatedly."""
    validate_table_name(table_name)
    if _table_ready.get(table_name):
        return
    with conn.cursor() as cur:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                id           BIGSERIAL PRIMARY KEY,
                action_type  TEXT NOT NULL,
                user_name    TEXT NOT NULL,
                doc_path     TEXT,
                section_id   TEXT,
                detail       JSONB,
                created_at   TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS {table_name}_created_idx "
            f"ON {table_name} (created_at DESC)"
        )
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS {table_name}_doc_idx "
            f"ON {table_name} (doc_path)"
        )
    conn.commit()
    _table_ready[table_name] = True
