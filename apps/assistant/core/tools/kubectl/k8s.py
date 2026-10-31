"""Shared plumbing for the kubectl tools: cluster config loading.

A public seam of `core.tools`: 2+ tool modules import it. Output truncation
lives in `text.py`, shared by all tool modules.

The kubectl tools are only on the surface when a cluster is reachable at all
(`cluster_configured()`): a kubeconfig file at KUBECONFIG, or the in-cluster
service account. A box without Kubernetes never offers the model a tool that
can only fail. Give the kubeconfig a read-only role; anything the model tries
to read outside it returns 403 Forbidden.

`default_namespace()` is ASSISTANT_NAMESPACE, the namespace a tool reads when
the model names none.

FAILURE POLICY: errors propagate to the tool executor; the registry's
defended Tier-2 catch turns them into text the LLM can react to.
"""
from __future__ import annotations

import os
import pathlib


def cluster_configured() -> bool:
    """True when a kubeconfig file or an in-cluster service account exists."""
    if os.environ.get("KUBERNETES_SERVICE_HOST"):
        return True
    path = os.environ.get("KUBECONFIG", "").strip()
    return bool(path) and pathlib.Path(path).is_file()


def default_namespace() -> str:
    """The namespace a kubectl tool reads when the model names none."""
    return os.environ.get("ASSISTANT_NAMESPACE", "").strip() or "default"


def load_config_once() -> None:
    # Lazy cluster dep: the package must import, and the registry seam must
    # build, without the kubernetes client installed; only an actual tool call
    # needs it.
    from kubernetes import config as _k8s_config  # noqa: PLC0415

    try:
        _k8s_config.load_incluster_config()
    except _k8s_config.ConfigException:
        # Outside a cluster: the kubeconfig at KUBECONFIG. A missing one
        # raises loudly.
        _k8s_config.load_kube_config()
