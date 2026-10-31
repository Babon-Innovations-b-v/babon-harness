"""dashkit.core.sync: sync-status table and heartbeat endpoint factory.

A dashboard can track one external "did the scheduled job run?" signal,
for example a nightly export or backup script that reports in when it
finishes. The script POSTs ``{"status": "ok", "duration_ms": 1234}`` to
the dashboard's heartbeat route with a bearer token; the dashboard shows
the last run in its inspector panel. The schema is identical per domain;
the heartbeat endpoint is built per table by ``make_heartbeat_router``.

The endpoint is bearer-token authenticated, and the shipped Caddyfile
answers ``/api/internal/*`` with 404 at the edge, so only callers on the
docker network or the host reach it.

Module map (one public callable per file):

    make_heartbeat_router.py  POST heartbeat router factory (+ SyncHeartbeat model)
    fetch_sync_status.py      read the single-row status payload
    table.py                  ensure_sync_status_table(conn, table_name), lazy
                              single-row table bootstrap

FAILURE POLICY: heartbeat writes PROPAGATE as HTTP errors (503 on
missing token or database), so a reporter knows its report was dropped.
Table bootstrap is best-effort (logged) because the read path degrades
to ``{"status": "stale"}`` anyway.
"""
from __future__ import annotations

from dashkit.core.sync.fetch_sync_status import (
    fetch_sync_status,
)
from dashkit.core.sync.make_heartbeat_router import (
    SyncHeartbeat,
    make_heartbeat_router,
)
from dashkit.core.sync.table import (
    ensure_sync_status_table,
)

__all__ = [
    "SyncHeartbeat",
    "ensure_sync_status_table",
    "fetch_sync_status",
    "make_heartbeat_router",
]
