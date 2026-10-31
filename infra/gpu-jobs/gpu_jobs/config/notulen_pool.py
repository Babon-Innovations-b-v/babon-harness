"""The GPU pools a notulen pod may land on, read at CALL time.

``GPU_POOL`` names the Kubernetes node pool (or a comma-separated list of
pools, the preferred one first) created for transcription. A cloud node pool
lives in one zone, and a zone can run out of GPU stock, so listing a second
pool in another zone gives a meeting somewhere else to go. The pools carry
the taint ``workload=notulen`` so nothing else lands on them, and the label
``k8s.scaleway.com/pool-name`` the affinity matches on (Scaleway Kapsule sets
it on every node; on another provider set ``GPU_POOL_LABEL``).

FAILURE POLICY: pure env reads, no I/O; a ``GPU_POOL`` that names no pool
raises ValueError, because an empty list would let the pod land nowhere and
wait for ever.
"""

from __future__ import annotations

import os

_DEFAULT_POOL = "notulen-gpu"

#: The taint the notulen pools apply; the pod must tolerate it to schedule.
NOTULEN_POOL_TAINT_KEY = "workload"
NOTULEN_POOL_TAINT_VALUE = "notulen"


def notulen_pool_names() -> tuple[str, ...]:
    """Every pool a notulen GPU pod may land on, preferred pool first."""
    raw = os.environ.get("GPU_POOL")
    if raw is None:
        return (_DEFAULT_POOL,)
    names = tuple(name.strip() for name in raw.split(",") if name.strip())
    if not names:
        raise ValueError(f"GPU_POOL={raw!r} names no pool")
    return names


def pool_label() -> str:
    """The node label whose value is the pool name."""
    return os.environ.get("GPU_POOL_LABEL") or "k8s.scaleway.com/pool-name"
