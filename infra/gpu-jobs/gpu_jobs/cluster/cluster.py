"""Configured-cluster accessor for code outside this package.

The dashboard's live-Job matchers (startup recovery, the dead-job watch, the
health check) need the same kubeconfig bootstrap, one-retry-on-401 call
wrapper and namespace the creators use. ``cluster()`` is the one public door
to them.

What is NOT here: Job manifests and dispatch policy.

FAILURE POLICY: Tier 1. The config bootstrap raises when no source loads;
``handle.call`` retries exactly once on 401 and otherwise propagates
ApiException.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .ensure_config import ensure_config
from .k8s_call import k8s_call
from .namespace import namespace
from ..security.worker_pod_security_context import worker_pod_security_context
from ..security.worker_security_context import worker_security_context


@dataclass(frozen=True)
class ClusterHandle:
    """What a caller outside this package may take from it.

    Fields are the collaborators themselves, not copies: ``call`` IS the
    creators' retry wrapper and the two context factories ARE the creators'
    hardening posture.
    """

    namespace: str
    call: Callable[..., Any]
    worker_security_context: Callable[[], Any]
    worker_pod_security_context: Callable[[], Any]


def cluster() -> ClusterHandle:
    """Bootstrap K8s config (idempotent) and return the configured handle.

    ``namespace`` is the env value at THIS call; re-call ``cluster()``
    instead of caching a handle across env changes. Construct kubernetes API
    objects (``client.BatchV1Api()`` etc.) only AFTER this returns;
    they snapshot the default Configuration at construction.
    """
    ensure_config()
    return ClusterHandle(
        namespace=namespace(),
        call=k8s_call,
        worker_security_context=worker_security_context,
        worker_pod_security_context=worker_pod_security_context,
    )
