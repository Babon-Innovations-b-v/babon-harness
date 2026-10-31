"""FastAPI app factory for dashkit dashboards.

The smallest possible "give me a dashboard" function: pass a
``DashkitConfig``, get back a wired-up FastAPI app with the standard
dashkit endpoints (audit log, AI calls, sync, inspector) plus the
shared frontend static-asset route. New dashboards add domain-specific
endpoints on top of the returned ``app``.

What this module does NOT own: the static route implementation lives in
``core/_frontend_static.py``; audit reads in ``core/audit``; sync
status in ``core/sync``; health checks in ``core/inspector.py``; the
AI-calls table in ``dashkit.ai``.

FAILURE POLICY: routes fail open per route. DB-unavailable returns an
empty payload (audit-log, ai-calls) or an explicit 503 (health), never
a crashed app. The missing-frontend swallow at mount time is the one
boot-time concession, documented at the site.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from dashkit.core import audit as _audit
from dashkit.core._frontend_static import (
    _make_frontend_router,
)
from dashkit.core.db import get_db
from dashkit.core.inspector import HealthCheck, run_checks
from dashkit.core.sync import (
    fetch_sync_status,
    make_heartbeat_router,
)


# Frozen: the config is assembled once at the dashboard entrypoint;
# nothing mutates it after construction.
@dataclass(frozen=True)
class DashkitConfig:
    """Per-domain configuration for ``make_dashboard_app``."""

    domain: str  # e.g. "notulen"
    title: str  # FastAPI title
    activity_table: str  # e.g. "notulen_activity"
    ai_calls_table: str  # e.g. "notulen_ai_calls"
    health_checks: list[HealthCheck] = field(default_factory=list)
    cors_origins: list[str] = field(default_factory=lambda: ["*"])
    # Optional: prefix for file-path links in the UI. Empty → no
    # links rendered. Example: "https://github.com/<owner>/<repo>/blob/main"
    github_blob_base: str = ""
    # Optional: name of the shared architecture table. Defaults to the
    # domain-neutral name so multiple dashboards can share one tree.
    architecture_table: str = "dashkit_architecture"
    # Optional: skip the frontend static-route mount. Off by default;
    # only flip this if a caller wants to wire its own static handler.
    mount_frontend: bool = True
    # Optional: a scheduled job that reports in (see ``dashkit.core.sync``).
    # Empty table name → no heartbeat route and no sync inspector row.
    sync_status_table: str = ""  # e.g. "backup_sync_status"
    sync_token_env_var: str = ""  # e.g. "SYNC_HEARTBEAT_TOKEN"


def make_dashboard_app(config: DashkitConfig) -> FastAPI:
    """Build and return a FastAPI app wired with dashkit primitives.

    The returned app has the following routes pre-mounted:

    - ``GET  /api/audit-log``           recent audit rows
    - ``GET  /api/inspector/sync``      single sync-status row (only with
      ``config.sync_status_table``)
    - ``GET  /api/inspector/health``    runs ``config.health_checks``
    - ``GET  /api/inspector/ai-calls``  recent AI calls + aggregates
    - ``POST /api/internal/sync-heartbeat`` bearer-token heartbeat (only
      with ``config.sync_status_table``)
    - ``GET  /static/dashkit/{filename:path}`` frontend static assets
      (skipped if ``config.mount_frontend=False``)

    The caller adds domain-specific endpoints by decorating the returned
    app directly. Tables are created lazily on first use.
    """
    app = FastAPI(title=config.title)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if config.sync_status_table:
        app.include_router(
            make_heartbeat_router(
                table_name=config.sync_status_table,
                token_env_var=config.sync_token_env_var,
            )
        )

    if config.mount_frontend:
        try:
            app.include_router(_make_frontend_router())
        except RuntimeError:
            # Best-effort swallow: frontend not present in this environment
            # (e.g. a unit test running off a stripped install). Nothing
            # else in dashkit depends on this route.
            pass

    @app.get("/api/audit-log")
    def audit_log(limit: int = 100):
        conn = get_db()
        if not conn:
            return {"activity": [], "total": 0}
        try:
            rows = _audit.fetch_activity(conn, config.activity_table, limit=limit)
            return {"activity": rows, "total": len(rows)}
        finally:
            conn.close()

    if config.sync_status_table:
        @app.get("/api/inspector/sync")
        def inspector_sync():
            conn = get_db()
            if not conn:
                return {"status": "unknown", "reason": "db unavailable"}
            try:
                return fetch_sync_status(conn, config.sync_status_table)
            finally:
                conn.close()

    @app.get("/api/inspector/health")
    def inspector_health():
        conn = get_db()
        if not conn:
            raise HTTPException(status_code=503, detail="Database unavailable")
        try:
            results = run_checks(conn, config.health_checks)
            return {"checks": results}
        finally:
            conn.close()

    @app.get("/api/inspector/ai-calls")
    def inspector_ai_calls(since_hours: int = 24, limit: int = 200):
        conn = get_db()
        if not conn:
            return {"rows": [], "totals": {}, "by_run": []}
        try:
            # Lazy import breaks the core/ai import cycle: ai needs
            # core.identifiers, and core/__init__ imports this file, so a
            # module-scope ai import here deadlocks package init.
            from dashkit.ai import (  # noqa: PLC0415
                ensure_ai_calls_table,
            )
            ensure_ai_calls_table(conn, config.ai_calls_table)
            since = datetime.now(timezone.utc).timestamp() - since_hours * 3600
            since_dt = datetime.fromtimestamp(since, tz=timezone.utc)

            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT id, run_id, purpose, model, doc_path, "
                    f"input_tokens, output_tokens, cost_estimate, "
                    f"duration_ms, success, error, created_at "
                    f"FROM {config.ai_calls_table} "
                    f"WHERE created_at >= %s "
                    f"ORDER BY created_at DESC LIMIT %s",
                    (since_dt, min(max(limit, 1), 1000)),
                )
                rows = [
                    {
                        "id": row[0],
                        "run_id": str(row[1]) if row[1] else None,
                        "purpose": row[2],
                        "model": row[3],
                        "doc_path": row[4],
                        "input_tokens": row[5],
                        "output_tokens": row[6],
                        "cost_estimate": float(row[7]) if row[7] is not None else 0.0,
                        "duration_ms": row[8],
                        "success": row[9],
                        "error": row[10],
                        "timestamp": row[11].isoformat() if row[11] else None,
                    }
                    for row in cur.fetchall()
                ]

                cur.execute(
                    f"SELECT COUNT(*), COALESCE(SUM(cost_estimate),0), "
                    f"COALESCE(SUM(input_tokens),0), "
                    f"COALESCE(SUM(output_tokens),0), "
                    f"COALESCE(AVG(duration_ms),0), "
                    f"SUM(CASE WHEN success THEN 0 ELSE 1 END) "
                    f"FROM {config.ai_calls_table} WHERE created_at >= %s",
                    (since_dt,),
                )
                agg = cur.fetchone() or (0, 0, 0, 0, 0, 0)
                totals = {
                    "calls": int(agg[0] or 0),
                    "cost_estimate": float(agg[1] or 0),
                    "input_tokens": int(agg[2] or 0),
                    "output_tokens": int(agg[3] or 0),
                    "avg_duration_ms": float(agg[4] or 0),
                    "failures": int(agg[5] or 0),
                }

                cur.execute(
                    f"SELECT run_id, COUNT(*), "
                    f"COALESCE(SUM(cost_estimate),0), "
                    f"COALESCE(SUM(input_tokens+output_tokens),0), "
                    f"MIN(created_at), MAX(created_at), "
                    f"SUM(CASE WHEN success THEN 0 ELSE 1 END) "
                    f"FROM {config.ai_calls_table} "
                    f"WHERE created_at >= %s AND run_id IS NOT NULL "
                    f"GROUP BY run_id ORDER BY MAX(created_at) DESC LIMIT 20",
                    (since_dt,),
                )
                by_run = [
                    {
                        "run_id": str(row[0]),
                        "calls": int(row[1]),
                        "cost": float(row[2] or 0),
                        "tokens": int(row[3] or 0),
                        "started_at": row[4].isoformat() if row[4] else None,
                        "last_at": row[5].isoformat() if row[5] else None,
                        "failures": int(row[6] or 0),
                    }
                    for row in cur.fetchall()
                ]
            return {
                "rows": rows,
                "totals": totals,
                "by_run": by_run,
                "since_hours": since_hours,
            }
        finally:
            conn.close()

    return app
