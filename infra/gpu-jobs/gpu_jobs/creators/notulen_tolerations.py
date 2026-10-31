"""The tolerations of a notulen GPU pod: the GPU taint and the notulen pools'.

Shared by the notulen Job and its GPU placeholder with ``notulen_affinity``.

FAILURE POLICY: pure manifest building, no I/O, nothing to swallow.
"""

from __future__ import annotations

from kubernetes import client

from ..config.notulen_pool import (
    NOTULEN_POOL_TAINT_KEY,
    NOTULEN_POOL_TAINT_VALUE,
)


def notulen_tolerations() -> list[client.V1Toleration]:
    """The GPU operator's taint plus the notulen pools' own taint.

    A toleration only permits; ``notulen_affinity`` is what keeps the pod off
    every other tainted pool.
    """
    return [
        client.V1Toleration(key="nvidia.com/gpu", operator="Exists", effect="NoSchedule"),
        client.V1Toleration(
            key=NOTULEN_POOL_TAINT_KEY,
            value=NOTULEN_POOL_TAINT_VALUE,
            operator="Equal",
            effect="NoSchedule",
        ),
    ]
