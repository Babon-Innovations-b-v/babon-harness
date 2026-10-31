"""A notulen Job waits for a GPU node for as long as it takes, and its run is
still capped once a node has it.

WHAT IT PINS. `gpu_jobs.create_notulen_job`, through its public
interface: the Job manifest it posts. Only the HTTP POST is replaced by a
recorder; the kubeconfig bootstrap and the client's own serialiser run for real,
so the dict read here is the JSON body the API server would receive.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From the
Kubernetes API reference, not from this package. `JobSpec.activeDeadlineSeconds`
is measured from the Job's `status.startTime`, which the Job controller sets
when it first handles the Job, so it counts the time the pod sits Pending with
no node. `PodSpec.activeDeadlineSeconds` is measured from the pod's
`status.startTime`, "the time at which the object was acknowledged by the
Kubelet", and only the kubelet of the node the pod was bound to can do that, so
a pod no node has taken never starts that clock. A Job that must wait out a GPU
stock-out therefore carries no Job-level deadline, and the cap on a hung worker
has to be a positive pod-level deadline. No value is frozen: 4 h is a knob.

WHAT IT WAS PROVED AGAINST. A Job-level 4 h deadline put back next to the
TTL.

GUARDS. A meeting Pending on a GPU stock-out, killed at its Job deadline
before any node came.
"""
from __future__ import annotations

import base64
from typing import Any

from kubernetes import client

from gpu_jobs import create_notulen_job
from gpu_jobs.cluster import ensure_config as ensure_config_module

# A kubeconfig that parses and points nowhere; only the POST is intercepted.
_DEAD_KUBECONFIG = """apiVersion: v1
kind: Config
clusters:
- name: nowhere
  cluster:
    server: https://127.0.0.1:1
    insecure-skip-tls-verify: true
contexts:
- name: nowhere
  context: {cluster: nowhere, user: nowhere}
current-context: nowhere
users:
- name: nowhere
  user: {token: not-a-real-token}
"""


def _notulen_manifest(monkeypatch) -> dict[str, Any]:
    posted: dict[str, Any] = {}

    def recorder(self, namespace=None, body=None, **kwargs):
        posted["job"] = body
        return body

    monkeypatch.setattr(client.BatchV1Api, "create_namespaced_job", recorder)
    monkeypatch.setenv(
        "KUBECONFIG_B64", base64.b64encode(_DEAD_KUBECONFIG.encode()).decode()
    )
    monkeypatch.setenv("NOTULEN_WORKER_IMAGE", "registry.example.com/harness/notulen-worker:v1")
    monkeypatch.setattr(ensure_config_module, "_configured", False)
    previous_default = client.Configuration.get_default_copy()
    try:
        create_notulen_job(
            "00000000-1111-4222-8333-444444444444",
            "notulen/audio/2026-01-15-call.webm",
            "Call",
            "2026-01-15",
            count_recent_jobs=lambda: 0,
        )
        return client.ApiClient().sanitize_for_serialization(posted["job"])
    finally:
        client.Configuration.set_default(previous_default)


def test_a_notulen_job_waits_for_a_gpu_without_a_deadline_and_its_run_is_still_capped(
    monkeypatch,
) -> None:
    """No clock runs while the pod waits for a node; one runs once it has one."""
    manifest = _notulen_manifest(monkeypatch)

    assert "activeDeadlineSeconds" not in manifest["spec"], (
        "a Job-level deadline counts the wait for a GPU node, so a meeting that "
        "waits out a stock-out is killed before it is ever transcribed"
    )
    pod_deadline = manifest["spec"]["template"]["spec"].get("activeDeadlineSeconds")
    assert isinstance(pod_deadline, int) and pod_deadline > 0, (
        "without a pod-level deadline a hung worker holds a GPU for ever"
    )
