"""Give back the GPU ``warm_gpu`` held, once the recording no longer needs it.

FAILURE POLICY: Tier-2, fail-open. Any error is logged and dropped: the
placeholder then ends on its own at its time limit, or is preempted by the
notulen Job it was holding the GPU for.
"""
from __future__ import annotations

import logging

from apps.notulen.app.shared.config import gpu_enabled

logger = logging.getLogger("notulen")


def release_gpu(key: str) -> None:
    """Delete the GPU placeholder for the recording ``key``, if there is one."""
    if not gpu_enabled():
        return
    try:
        # Lazy: the dashboard boots without the kubernetes package.
        from gpu_jobs import release_notulen_gpu  # noqa: PLC0415
        release_notulen_gpu(key)
    except Exception:
        # Documented Tier-2 swallow (see module FAILURE POLICY).
        logger.exception("Could not release the notulen GPU for %s", key)
