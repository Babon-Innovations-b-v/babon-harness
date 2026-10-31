"""`kubectl` check: a Deployment has >=1 ready replica.

`component.target` is `namespace/name`. Reads the Deployment via the
Python kubernetes client through the shared `tools.k8s.load_config_once`
seam (in-cluster config in the pod, kubeconfig in dev). >=1 ready
replica = up; 0 desired replicas = parked, reported up; 0 ready = down;
an API error reaching the cluster = down
(the cluster surface is the component here). Check-module grammar: one
public `check`.

FAILURE POLICY: a kubernetes ApiException returns a `down` CheckResult;
an unparseable target returns `unknown`. The kubernetes client is
imported lazily (module standard §3), mirroring `core/tools/kubectl/kubectl_get.py`.
"""
from __future__ import annotations

from typing import Any

from apps.assistant.core.monitor.limits import CHECK_TIMEOUT_SECONDS
from apps.assistant.core.monitor.component import (
    DOWN,
    UNKNOWN,
    UP,
    CheckResult,
    Component,
)
from apps.assistant.core.tools.kubectl.k8s import load_config_once


def _parse_target(target: str) -> tuple[str, str] | None:
    parts = target.split("/", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return parts[0], parts[1]


def check(component: Component, prior_row: dict[str, Any] | None = None) -> CheckResult:
    parsed = _parse_target(component.target)
    if parsed is None:
        return CheckResult(UNKNOWN, f"bad target {component.target!r} (want namespace/name)")
    namespace, name = parsed

    # Lazy cluster dep (module standard §3): only an actual probe needs it.
    from kubernetes import client as _k8s_client  # noqa: PLC0415
    from kubernetes.client.exceptions import ApiException  # noqa: PLC0415

    load_config_once()
    apps = _k8s_client.AppsV1Api()
    try:
        # The kubernetes client passes timeout=None to urllib3 unless the
        # caller supplies one, so without this a hung API socket would park
        # the sweep THREAD, and the sweep is what every other liveness answer
        # is read from. The assistant would then answer "everything is up"
        # indefinitely, from the component that had died. Neither the k8s probes nor the VM deadman would have
        # noticed: both hit a /health that returns uptime and nothing else.
        deployment = apps.read_namespaced_deployment(
            name=name,
            namespace=namespace,
            _request_timeout=CHECK_TIMEOUT_SECONDS,
        )
    except ApiException as exc:
        return CheckResult(DOWN, f"k8s API {exc.status}: {name}")

    if deployment.spec.replicas == 0:
        # Scaled to 0 on purpose: parked, not down.
        return CheckResult(UP, "parked: 0 replicas desired")
    ready = deployment.status.ready_replicas or 0
    if ready >= 1:
        return CheckResult(UP, f"{ready} ready")
    return CheckResult(DOWN, "0 ready replicas")
