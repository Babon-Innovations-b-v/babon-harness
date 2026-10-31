"""Per-domain ``{domain}_ai_calls`` accounting table: lazy create.

FAILURE POLICY: best-effort. Accounting must never break the
feature making the Claude call. Every swallow logs at WARNING so a
silently-dead cost log still leaves a journal trail.
"""
from __future__ import annotations

import logging

from dashkit.core import validate_table_name

logger = logging.getLogger("dashkit.ai")

# Per-table "already created?" flags so the lazy CREATE TABLE only runs
# once per process per table.
_table_ready: dict[str, bool] = {}


def ensure_ai_calls_table(conn, table_name: str) -> None:
    """Lazily create ``{table_name}`` on first use."""
    validate_table_name(table_name)
    if _table_ready.get(table_name):
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    id              BIGSERIAL PRIMARY KEY,
                    run_id          UUID,
                    purpose         TEXT NOT NULL,
                    model           TEXT NOT NULL,
                    doc_path        TEXT,
                    input_tokens    INTEGER NOT NULL,
                    output_tokens   INTEGER NOT NULL,
                    cost_estimate   NUMERIC(10,6) NOT NULL,
                    duration_ms     INTEGER,
                    success         BOOLEAN NOT NULL,
                    error           TEXT,
                    created_at      TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS {table_name}_run_idx "
                f"ON {table_name} (run_id)"
            )
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS {table_name}_created_idx "
                f"ON {table_name} (created_at DESC)"
            )
        conn.commit()
        _table_ready[table_name] = True
    except Exception as exc:
        # Best-effort swallow: table bootstrap is observability plumbing; the
        # insert below will fail-and-log too if the table truly can't exist.
        logger.warning("ensure_ai_calls_table(%s) failed: %s", table_name, exc)
        try:
            conn.rollback()
        except Exception:
            logger.warning("rollback after failed ensure_ai_calls_table also failed")
