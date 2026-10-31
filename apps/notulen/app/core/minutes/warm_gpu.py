"""Ask for the notulen GPU when a recording starts, not when it ends.

A cloud GPU node can take a long time to power on when the zone is short of
cards. Asking at the start of the meeting moves that wait inside the meeting,
so the notulen Job finds a node ready when the recording is finalized.

FAILURE POLICY: Tier-2, fail-open. Runs on its own thread so the start of a
recording never waits on the cluster, and any error is logged and dropped: a
missed warm-up costs only the cold-start wait.
"""
from __future__ import annotations

import logging
import threading

from apps.notulen.app.shared.config import gpu_enabled

logger = logging.getLogger("notulen")


def _warm(key: str) -> None:
    try:
        # Lazy: the dashboard boots without the kubernetes package.
        from gpu_jobs import warm_notulen_gpu  # noqa: PLC0415
        pod_name = warm_notulen_gpu(key)
        logger.info("Warming a notulen GPU for %s (%s)", key, pod_name)
    except Exception:
        # Documented Tier-2 swallow (see module FAILURE POLICY).
        logger.exception("Could not warm a notulen GPU for %s", key)


def warm_gpu(key: str) -> None:
    """Start holding a notulen GPU for the recording ``key``, in the background."""
    if not gpu_enabled():
        return
    threading.Thread(target=_warm, args=(key,), daemon=True).start()
