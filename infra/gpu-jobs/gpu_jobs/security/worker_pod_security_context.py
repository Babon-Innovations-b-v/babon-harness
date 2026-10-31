"""Pod-level SecurityContext shared by every notulen GPU pod.

The container-level twin lives in ``worker_security_context.py``. One home,
so the Job and its placeholder cannot drift on the hardening posture.

FAILURE POLICY: pure object construction: nothing to swallow.
"""

from __future__ import annotations

from kubernetes import client


def worker_pod_security_context() -> "client.V1PodSecurityContext":
    """Pod-level security context.

    fsGroup: 1000 makes emptyDir volumes (/dev/shm, /scratch) owned by
    gid 1000 so the non-root worker user (uid 1000 in the image) can
    write to them. Without this, mounting /dev/shm as a Memory emptyDir
    gives it root-only permissions and the worker can't create shared
    memory segments.
    """
    return client.V1PodSecurityContext(fs_group=1000)
