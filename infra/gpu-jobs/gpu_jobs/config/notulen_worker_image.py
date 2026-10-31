"""Notulen GPU worker image, read at CALL time.

``NOTULEN_WORKER_IMAGE`` is the full image reference ``infra/gpu/build-worker.sh``
printed, with a pinned tag. Never ``:latest``: the Job pulls
``IfNotPresent``, so a moving tag leaves nodes on a stale image.

FAILURE POLICY: raises KeyError when unset, because a Job without an image
would sit in ``InvalidImageName`` and the meeting would never transcribe.
"""

from __future__ import annotations

import os


def notulen_worker_image() -> str:
    """The pinned notulen GPU worker image."""
    image = os.environ.get("NOTULEN_WORKER_IMAGE", "").strip()
    if not image:
        raise KeyError("NOTULEN_WORKER_IMAGE")
    return image
