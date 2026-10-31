"""Try to dispatch a Kubernetes GPU notulen-worker job.

The gate between the GPU path and the local CPU path in
``core/minutes/process_job.py``. The GPU path runs only when
``GPU_ENABLED=1`` and a cluster key (``KUBECONFIG_B64``) is present. The
kubernetes client imports lazily, so the dashboard boots without it.

FAILURE POLICY: fail-OPEN by design. Any dispatch error returns False so the
recording still transcribes on CPU (when the ``whisper`` extra is installed),
and the failure pages the assistant, throttled to once an hour, because a
silent CPU fallback turns a ten-minute meeting into hours of waiting. The
notifier itself is a documented Tier-2 swallow.
"""
from __future__ import annotations

import logging
import time

from apps.notulen.app.shared.assistant_door import notify_assistant
from apps.notulen.app.shared.config import gpu_enabled

logger = logging.getLogger("notulen")

# One page per hour at most. Module-global; resets on container restart,
# which is fine because a restart is itself worth re-paging on.
_CPU_FALLBACK_ALERT_THROTTLE_SEC = 3600
_last_cpu_fallback_alert_ts: float = 0.0


def _alert_cpu_fallback(job_id: str, reason: str) -> None:
    """Page when the GPU tier is on but dispatch failed."""
    global _last_cpu_fallback_alert_ts
    now = time.time()
    if now - _last_cpu_fallback_alert_ts < _CPU_FALLBACK_ALERT_THROTTLE_SEC:
        return
    _last_cpu_fallback_alert_ts = now
    try:
        notify_assistant(
            "notulen: GPU dispatch failed, running on CPU",
            f"Job: {job_id}\n"
            f"Reason: {reason}\n\n"
            "The dashboard fell back to local CPU transcription. Real meetings "
            "will take hours instead of minutes. Check the dashboard's "
            "kubeconfig and its RBAC in GPU_NAMESPACE; throttled to one page "
            "per hour.",
        )
    except Exception:
        # Documented Tier-2 swallow (see module FAILURE POLICY).
        logger.exception("Failed to page on CPU fallback for %s", job_id)


def try_dispatch_gpu(
    job_id: str,
    s3_key: str,
    title: str,
    meeting_date: str,
    attendees: list[str],
    agenda: str,
) -> bool:
    """Try to dispatch a Kubernetes GPU job. True if dispatched, else False."""
    if not gpu_enabled():
        return False
    try:
        # Lazy: the dashboard boots without the kubernetes package.
        from gpu_jobs import create_notulen_job  # noqa: PLC0415
        create_notulen_job(
            job_id=job_id,
            audio_key=s3_key,
            title=title,
            meeting_date=meeting_date,
            attendees=", ".join(attendees),
            agenda=agenda,
        )
        logger.info("Dispatched GPU job for %s", job_id)
        return True
    except Exception as exc:
        # Documented fail-open: the CPU path still produces the minutes.
        logger.warning("GPU dispatch failed, falling back to CPU: %s", exc)
        _alert_cpu_fallback(job_id, repr(exc)[:200])
        return False
