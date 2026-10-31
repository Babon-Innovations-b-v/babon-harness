"""Insert one ``{domain}_ai_calls`` accounting row.

FAILURE POLICY: best-effort. Accounting must never break the
feature making the Claude call. Every swallow logs at WARNING so a
silently-dead cost log still leaves a journal trail.
"""
from __future__ import annotations

import logging
from typing import Optional

from dashkit.ai.ensure_ai_calls_table import (
    ensure_ai_calls_table,
)
from dashkit.core.db import get_db

logger = logging.getLogger("dashkit.ai")


def log_ai_call(
    conn,
    table_name: str,
    *,
    run_id: Optional[str],
    purpose: str,
    model: str,
    doc_path: Optional[str],
    input_tokens: int,
    output_tokens: int,
    cost_estimate: float,
    duration_ms: int,
    success: bool,
    error: Optional[str],
) -> None:
    """Insert one ``{table_name}`` row. Fails open, never raises.

    Opens a short-lived connection if ``conn`` is None so this works
    inside ThreadPoolExecutors that can't share a single connection.
    """
    owns_conn = False
    try:
        if conn is None:
            conn = get_db()
            if conn is None:
                logger.warning("log_ai_call skipped: database unavailable")
                return
            owns_conn = True
        ensure_ai_calls_table(conn, table_name)
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {table_name} "
                f"(run_id, purpose, model, doc_path, input_tokens, output_tokens, "
                f"cost_estimate, duration_ms, success, error) "
                f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    run_id,
                    purpose,
                    model,
                    doc_path,
                    input_tokens,
                    output_tokens,
                    cost_estimate,
                    duration_ms,
                    success,
                    error,
                ),
            )
        conn.commit()
    except Exception as exc:
        # Best-effort swallow: a broken cost log must never break the feature
        # making the Claude call. Logged so Loki still shows the gap.
        logger.warning("log_ai_call failed (swallowed): %s", exc)
        try:
            if conn is not None:
                conn.rollback()
        except Exception:
            logger.warning("rollback after failed log_ai_call also failed")
    finally:
        if owns_conn and conn is not None:
            try:
                conn.close()
            except Exception:
                logger.warning("closing short-lived ai-log connection failed")
