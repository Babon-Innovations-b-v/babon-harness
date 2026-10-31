"""One-retry-on-401 wrapper around any kubernetes-client API call.

What is NOT here: the config bootstrap itself. ``ensure_config.py`` owns the
kubeconfig dance and the BearerToken alias; this wrapper only forces a reload
(``ensure_config(force=True)``) when a call comes back 401 with a stale token
after rotation.

FAILURE POLICY: Tier 1. Retries exactly once on 401 and otherwise propagates
ApiException to the caller.
"""

from __future__ import annotations

import logging

from kubernetes import client

from .ensure_config import ensure_config

log = logging.getLogger(__name__)


def k8s_call(fn, *args, **kwargs):
    """Call a K8s API function with one retry on auth failure (401)."""
    try:
        return fn(*args, **kwargs)
    except client.ApiException as exc:
        if exc.status == 401:
            log.warning("K8s auth failed (401), re-initializing config and retrying")
            ensure_config(force=True)
            return fn(*args, **kwargs)
        raise
