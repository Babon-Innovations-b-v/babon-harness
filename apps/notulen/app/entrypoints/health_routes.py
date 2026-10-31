"""Health endpoints: two endpoints, two purposes.

- ``/healthz`` is the cheap liveness probe the blackbox exporter scrapes.
  DB ping only, no upstream calls, schema
  ``{ok: bool, checks: [{name, ok, ms}]}``. Returns HTTP 200 whenever the
  app is alive; ``ok: false`` carries the bad news so the probe can fail on
  a body match.
- ``/api/health/notulen/full`` is the rich payload for the dashboard UI
  banner: DB, GPU cluster, and the 24 h success rate. It is never the probe
  path, because a slow cluster call would time the probe out.

FAILURE POLICY: health endpoints never raise: every check converts its
failure into the response body (that IS the product of this module). Each
swallow below is that documented conversion.
"""
from __future__ import annotations

import time

from fastapi import APIRouter

from dashkit.core.db import get_db

from apps.notulen.app.shared.config import gpu_enabled
from apps.notulen.app.shared.jobs_table import ensure_jobs_table

router = APIRouter()


def _db_ping_ms() -> tuple[bool, int]:
    """Cheap DB liveness: ``SELECT 1`` round-trip, no schema lookups."""
    started = time.monotonic()
    try:
        conn = get_db()
        if not conn:
            return False, int((time.monotonic() - started) * 1000)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        finally:
            conn.close()
    except Exception:
        # Documented swallow: the probe's job is to REPORT failure, not raise.
        return False, int((time.monotonic() - started) * 1000)
    return True, int((time.monotonic() - started) * 1000)


@router.get("/healthz")
def _healthz():
    """Cheap liveness probe for the blackbox exporter."""
    db_ok, db_ms = _db_ping_ms()
    return {"ok": db_ok, "checks": [{"name": "database", "ok": db_ok, "ms": db_ms}]}


def _check_gpu_cluster() -> dict:
    """Probe the K8s capability we actually use: namespace-scoped job list:
    instead of cluster-wide list_node, which a least-privilege kubeconfig may
    reject (403) even when dispatch works."""
    if not gpu_enabled():
        return {
            "name": "gpu",
            "ok": True,
            "note": "GPU tier off (GPU_ENABLED=0 or no KUBECONFIG_B64); CPU transcription",
        }
    try:
        # Lazy: the dashboard boots without the kubernetes package.
        from gpu_jobs import cluster  # noqa: PLC0415
        from kubernetes import client as k8s_client  # noqa: PLC0415
        handle = cluster()
        handle.call(
            k8s_client.BatchV1Api().list_namespaced_job,
            namespace=handle.namespace, limit=1, timeout_seconds=5,
        )
        return {"name": "gpu", "ok": True}
    except Exception as exc:
        # Documented swallow: degraded, CPU fallback still works.
        return {"name": "gpu", "ok": False, "error": str(exc)[:200]}


@router.get("/api/health/notulen/full")
def _health_notulen_full():
    """Aggregate health for the dashboard UI banner.

    Returns 200 always so the UI sees the JSON. Consumers look at the
    ``status`` field (``ok``/``degraded``/``broken``) and the per-check
    list. Never on the probe path: chained 5 s timeouts would flap it.
    """
    checks: list[dict] = []
    overall = "ok"

    # DB check
    try:
        conn = get_db()
        if not conn:
            raise RuntimeError("get_db returned None")
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        finally:
            conn.close()
        checks.append({"name": "database", "ok": True})
    except Exception as exc:
        checks.append({"name": "database", "ok": False, "error": str(exc)[:200]})
        overall = "broken"

    # K8s check (only meaningful when configured).
    gpu_check = _check_gpu_cluster()
    checks.append(gpu_check)
    if not gpu_check["ok"] and overall == "ok":
        overall = "degraded"  # CPU fallback still works

    # Recent job success rate (last 24h, ignore still-running)
    try:
        conn = get_db()
        if conn:
            try:
                ensure_jobs_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT "
                        "  SUM(CASE WHEN status = 'complete' THEN 1 ELSE 0 END), "
                        "  SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) "
                        "FROM notulen_jobs "
                        "WHERE created_at > NOW() - INTERVAL '24 hours' "
                        "  AND status IN ('complete', 'failed')"
                    )
                    row = cur.fetchone() or (0, 0)
                    complete, failed = int(row[0] or 0), int(row[1] or 0)
                total = complete + failed
                rate = (complete / total) if total else 1.0
                checks.append({
                    "name": "recent_jobs_24h",
                    "ok": rate >= 0.5 or total == 0,
                    "complete": complete,
                    "failed": failed,
                    "success_rate": round(rate, 2),
                })
                if total >= 3 and rate < 0.5 and overall == "ok":
                    overall = "degraded"
            finally:
                conn.close()
    except Exception as exc:
        # Documented swallow: report the check as failed, keep the banner up.
        checks.append({"name": "recent_jobs_24h", "ok": False, "error": str(exc)[:200]})

    return {"status": overall, "checks": checks}
