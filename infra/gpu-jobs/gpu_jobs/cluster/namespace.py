"""The namespace every notulen GPU object lives in, read at CALL time.

``GPU_NAMESPACE`` from ``config/harness.env`` (default ``notulen``). An
accessor, not a module constant, so a test can change it mid-run and the next
call sees it.

FAILURE POLICY: pure env read, no I/O, nothing to swallow.
"""

from __future__ import annotations

import os


def namespace() -> str:
    """Kubernetes namespace every Job and Pod in this package is submitted to."""
    return os.environ.get("GPU_NAMESPACE") or "notulen"
