"""Startup recovery of jobs interrupted by a dashboard restart.

Jobs running on the GPU path own their lifecycle in a K8s Job independent
of this dashboard: a dashboard restart (auto-deploy, secret-sync, OOM)
must NOT poison those rows. Only mark ``failed`` when the corresponding
K8s Job is gone or itself failed. Without this check, every dashboard
recreate would kill any in-flight transcription.

``recording`` sessions are NOT touched here: the browser holds the chunks
in IndexedDB, so a re-opened tab can resume the upload. The stale-cleanup
loop (``core/sessions/stale_cleanup.py``) retires those after 6 h.

FAILURE POLICY: the K8s liveness probe fails OPEN (an unreachable cluster
returns "all candidates live", so a flaky kubeconfig never mass-fails rows
that might be progressing); the DB write itself propagates (Tier-1).
"""
from __future__ import annotations

from dashkit.core.db import get_db

from apps.notulen.app.shared.config import gpu_enabled
from apps.notulen.app.shared.jobs_table import ensure_jobs_table


def recover_interrupted_jobs() -> None:
    """Mark orphaned in-flight jobs ``failed``; leave live GPU jobs alone."""
    conn = get_db()
    if not conn:
        return
    try:
        ensure_jobs_table(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM notulen_jobs "
                "WHERE status IN ('transcribing', 'structuring')"
            )
            candidates = [str(row[0]) for row in cur.fetchall()]

        if not candidates:
            return

        live_ids = _live_k8s_job_ids(candidates)
        orphans = [job_id for job_id in candidates if job_id not in live_ids]
        if not orphans:
            return

        with conn.cursor() as cur:
            # id is UUID; orphans is a list of str (the SELECT above str()s
            # each row). Cast the bound text[] to uuid[] so Postgres has a
            # uuid = uuid operator. Without the cast it raises "operator does
            # not exist: uuid = text" and crash-loops dashboard startup
            # whenever an orphan row is present.
            cur.execute(
                "UPDATE notulen_jobs SET status = 'failed', "
                "error = 'Server restarted during processing' "
                "WHERE id = ANY(%s::uuid[]) "
                "AND status IN ('transcribing', 'structuring')",
                (orphans,),
            )
        conn.commit()
    finally:
        conn.close()


def _live_k8s_job_ids(candidate_ids: list[str]) -> set[str]:
    """Return the subset of job IDs whose K8s Job is still active.

    On any K8s error (no kubeconfig, network blip, RBAC), returns all
    candidate IDs: fail open so an unreachable cluster never mass-fails
    rows that might actually be progressing.
    """
    if not gpu_enabled():
        return set(candidate_ids)
    try:
        # Lazy: the dashboard boots without the kubernetes package.
        from gpu_jobs import cluster, job_name  # noqa: PLC0415
        from kubernetes import client as k8s_client  # noqa: PLC0415
        handle = cluster()
        listing = handle.call(
            k8s_client.BatchV1Api().list_namespaced_job,
            namespace=handle.namespace,
            label_selector="app=notulen-worker",
            timeout_seconds=5,
        )
    except Exception:
        # Documented fail-open swallow (see module FAILURE POLICY).
        return set(candidate_ids)

    live_names: set[str] = set()
    for k8s_job in listing.items:
        status = k8s_job.status
        # A Job is "live" until it has Succeeded or Failed in its conditions.
        terminal = False
        for cond in (status.conditions or []):
            if cond.type in ("Complete", "Failed") and cond.status == "True":
                terminal = True
                break
        if not terminal:
            live_names.add(k8s_job.metadata.name)

    # Same (prefix, seed_chars) as gpu_jobs.create_notulen_job:
    # job_name() is the one home for the mangling grammar.
    return {
        job_id
        for job_id in candidate_ids
        if job_name("notulen", job_id, seed_chars=20) in live_names
    }
