"""Bearer-token heartbeat endpoint factory (one POST route per dashboard).

One public callable; ``SyncHeartbeat``, the pydantic body schema of the
route the factory builds, rides along as its signature type. The table bootstrap lives in
``sync/table.py``; the status read lives in ``fetch_sync_status.py``.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from dashkit.core.identifiers import validate_table_name
from dashkit.core.db import get_db
from dashkit.core.sync.table import (
    ensure_sync_status_table,
)


class SyncHeartbeat(BaseModel):
    status: str  # 'ok' / 'fail'
    duration_ms: int
    error: Optional[str] = None


def make_heartbeat_router(
    *,
    table_name: str,
    token_env_var: str,
    path: str = "/api/internal/sync-heartbeat",
) -> APIRouter:
    """Build a FastAPI router with one POST endpoint for sync heartbeats.

    Token is read from ``os.environ[token_env_var]`` at request time
    (NOT at import time) so misconfiguration can be fixed without a
    restart.
    """
    validate_table_name(table_name)
    router = APIRouter()

    @router.post(path)
    def sync_heartbeat(
        body: SyncHeartbeat,
        authorization: Optional[str] = Header(default=None),
    ):
        token = os.environ.get(token_env_var)
        if not token:
            raise HTTPException(
                status_code=503,
                detail=(
                    f"heartbeat not configured ({token_env_var} not set)"
                ),
            )
        if authorization != f"Bearer {token}":
            raise HTTPException(status_code=401, detail="invalid heartbeat token")
        if body.status not in ("ok", "fail"):
            raise HTTPException(status_code=400, detail="status must be 'ok' or 'fail'")

        conn = get_db()
        if not conn:
            raise HTTPException(status_code=503, detail="Database unavailable")
        try:
            ensure_sync_status_table(conn, table_name)
            now = datetime.now(timezone.utc)
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE {table_name} SET "
                    f"last_run_at = %s, last_run_status = %s, "
                    f"last_run_duration_ms = %s, last_run_error = %s "
                    f"WHERE id = 1",
                    (now, body.status, body.duration_ms, body.error),
                )
            conn.commit()
            return {"ok": True, "last_run_at": now.isoformat()}
        finally:
            conn.close()

    return router
