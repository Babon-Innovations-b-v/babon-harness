"""Give back the notulen GPU placeholder for one recording.

Called once the recording no longer needs it: its notulen Job has been
dispatched, or the recording was aborted. When the
Job has already preempted the placeholder, there is nothing left to delete.

FAILURE POLICY: Tier 1, ApiException propagates (through the single 401
retry), except 404: the placeholder is already gone, which is the state
this asks for.
"""

from __future__ import annotations

from kubernetes import client
from kubernetes.client.exceptions import ApiException

from ..cluster.ensure_config import ensure_config
from ..cluster.k8s_call import k8s_call
from ..cluster.namespace import namespace
from .warm_notulen_gpu import warm_notulen_gpu_name


def release_notulen_gpu(key: str) -> None:
    """Delete the placeholder Pod ``warm_notulen_gpu(key)`` submitted."""
    ensure_config()
    try:
        k8s_call(
            client.CoreV1Api().delete_namespaced_pod,
            name=warm_notulen_gpu_name(key),
            namespace=namespace(),
            grace_period_seconds=0,
        )
    except ApiException as exc:
        if exc.status != 404:
            raise
