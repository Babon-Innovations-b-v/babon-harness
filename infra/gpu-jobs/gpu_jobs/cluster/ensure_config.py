"""Kubeconfig bootstrap, idempotent, with the BearerToken alias.

Owns the config dance (the ``KUBECONFIG_B64`` env blob, in-cluster, or the
local kubeconfig file) and the BearerToken alias that kubernetes-client v36
needs: ``load_kube_config`` writes the token under api_key key
``authorization`` while every generated operation declares
``auth_settings=['BearerToken']``. Without the alias every API call goes out
anonymous, the cluster answers 403, and the dashboard silently degrades to
CPU transcription.

What is NOT here: the one-retry-on-401 call wrapper (``k8s_call.py``), which
calls ``ensure_config(force=True)`` after a stale-token 401.

FAILURE POLICY: Tier 1, raises when no config source loads.
"""

from __future__ import annotations

import base64
import os
import tempfile

from kubernetes import client, config

_configured = False


def ensure_config(*, force: bool = False) -> None:
    """Load Kubernetes config once (env blob, in-cluster, or local file).

    ``force=True`` re-loads even if already configured: the 401-retry path in
    ``k8s_call`` uses it after a token rotation invalidates the cached
    credentials.
    """
    global _configured
    if _configured and not force:
        return

    kubeconfig_data = os.environ.get("KUBECONFIG_B64") or os.environ.get("KUBECONFIG_DATA")
    if kubeconfig_data:
        decoded = base64.b64decode(kubeconfig_data)
        # One file per process, not one per machine: two processes writing a
        # shared path race, and the first reads back a config it never wrote.
        kc_path = os.path.join(tempfile.gettempdir(), f"kubeconfig-{os.getpid()}")
        with open(kc_path, "wb") as kubeconfig_file:
            kubeconfig_file.write(decoded)
        os.chmod(kc_path, 0o600)
        config.load_kube_config(config_file=kc_path)
    else:
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()

    # kubernetes-client 36 declares `auth_settings = ['BearerToken']` on every
    # operation, but load_kube_config writes the token under api_key key
    # `authorization`. Mirror the key, or every call goes out anonymous.
    cfg = client.Configuration.get_default_copy()
    if "authorization" in cfg.api_key and "BearerToken" not in cfg.api_key:
        cfg.api_key["BearerToken"] = cfg.api_key["authorization"]
        client.Configuration.set_default(cfg)

    _configured = True
