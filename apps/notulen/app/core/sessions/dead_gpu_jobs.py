"""Daemon loop that fails the row of a GPU job Kubernetes gave up on.

The GPU worker writes its own row, so when its pod dies without writing
(the pod's 4 h run cap, an OOM kill, a lost node) the row stays
``transcribing`` for ever and the meeting looks like it is still being
worked on. The startup hook in ``recovery.py`` only catches that after a
restart, so a dashboard that stays up needs this loop to see it.

Only a Job Kubernetes itself reports ``Failed`` counts, and a Job still
waiting for a GPU node never fails: the run cap sits on the pod and starts
when a node accepts it, so a meeting waits as long as a GPU takes to come.
A ``transcribing``
row with no Job at all is the CPU fallback at work, and is left alone. The
Job is deleted five minutes after it finishes (``ttl_seconds_after_finished``
in ``create_notulen_job``), so the poll runs well inside that window; a
dashboard that was down for all of it is ``recovery.py``'s case.

FAILURE POLICY: Tier-2 loop -- each tick swallows + logs and retries on the
next. The K8s read fails safe: an unreachable cluster answers "nothing
failed", so a kubeconfig flap can never fail a row. The row write inside a
tick propagates into that swallow.
"""
from __future__ import annotations

import logging
import time

from apps.notulen.app.core.sessions.alert_recording import (
    alert_gpu_job_died,
)
from apps.notulen.app.shared.config import gpu_enabled
from apps.notulen.app.shared.jobs_table import ensure_jobs_table
from dashkit.core.db import get_db

logger = logging.getLogger("notulen")

DEAD_JOB_CHECK_INTERVAL_SECS = 60


def failed_job_reasons(k8s_jobs) -> dict[str, str]:
    """{notulen job id: Kubernetes' reason} for every Job that has Failed."""
    reasons: dict[str, str] = {}
    for k8s_job in k8s_jobs:
        job_id = (k8s_job.metadata.labels or {}).get("job-id")
        for cond in (k8s_job.status.conditions or []):
            if job_id and cond.type == "Failed" and cond.status == "True":
                reasons[job_id] = cond.message or cond.reason or "GPU job failed"
    return reasons


def _list_notulen_k8s_jobs() -> list:
    """Every notulen-worker Job in the cluster; [] when it cannot be read."""
    if not gpu_enabled():
        return []
    try:
        # Lazy: the dashboard boots without the kubernetes package.
        from kubernetes import client as k8s_client

        from gpu_jobs import cluster
        handle = cluster()
        listing = handle.call(
            k8s_client.BatchV1Api().list_namespaced_job,
            namespace=handle.namespace,
            label_selector="app=notulen-worker",
            timeout_seconds=5,
        )
    except Exception:
        # Documented fail-safe swallow (see module FAILURE POLICY).
        logger.exception("could not list notulen K8s jobs")
        return []
    return listing.items


def fail_rows_of_dead_gpu_jobs(conn, reasons: dict[str, str]) -> None:
    """Mark each still-in-flight row of a failed Job ``failed`` and page once.

    The status guard in the UPDATE is the dedup: a row already failed, or
    one the worker finished after all, matches nothing and pages nothing.
    """
    for job_id, reason in reasons.items():
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE notulen_jobs SET status = 'failed', error = %s "
                "WHERE id = %s::uuid AND status IN ('transcribing', 'structuring') "
                "RETURNING title",
                (f"GPU job stopped: {reason}"[:2000], job_id),
            )
            row = cur.fetchone()
        conn.commit()
        if row:
            logger.info("GPU job for %s failed (%s), row marked failed", job_id, reason)
            alert_gpu_job_died(job_id, row[0], reason)


def watch_dead_gpu_jobs_loop() -> None:
    """Poll every DEAD_JOB_CHECK_INTERVAL_SECS for GPU jobs that failed."""
    while True:
        try:
            reasons = failed_job_reasons(_list_notulen_k8s_jobs())
            if reasons:
                conn = get_db()
                if conn:
                    try:
                        ensure_jobs_table(conn)
                        fail_rows_of_dead_gpu_jobs(conn, reasons)
                    finally:
                        conn.close()
        except Exception:
            # Tier-2 swallow (documented): the next tick retries.
            logger.exception("dead-GPU-job watch loop error")
        time.sleep(DEAD_JOB_CHECK_INTERVAL_SECS)
