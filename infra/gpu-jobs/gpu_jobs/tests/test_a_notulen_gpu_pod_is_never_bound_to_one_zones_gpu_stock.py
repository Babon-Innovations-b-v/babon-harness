"""A notulen GPU pod may land in more than one zone, so one zone's GPU stock-out
never leaves a meeting waiting for a node that cannot come.

WHAT IT PINS. `gpu_jobs.create_notulen_job` and `gpu_jobs.warm_notulen_gpu`,
through their public interfaces: the manifests they post. Only the two HTTP
POSTs are replaced by recorders.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The zone of each
pool is a fact about the cloud, written out below: a node pool lives in one
zone and the autoscaler never moves it. With `GPU_POOL` naming a pool in each
of two zones, Kubernetes ORs the terms of a required node affinity, so the
pools a pod may land on are the values of its `In` expressions on the pool
label; mapped to zones they must name two. A preferred term with the highest
weight is what the scheduler ranks first among nodes that fit, and it must be
the first pool listed. The placeholder must accept exactly the pools the Job
accepts, or it warms a node the Job cannot use.

WHAT IT WAS PROVED AGAINST. The affinity built from the first pool only, a
single-zone pin.
"""
from __future__ import annotations

import base64
from typing import Any

from kubernetes import client

from gpu_jobs import create_notulen_job, warm_notulen_gpu
from gpu_jobs.cluster import ensure_config as ensure_config_module

_POOL_LABEL = "k8s.scaleway.com/pool-name"
# Where each GPU pool lives, as the cluster carries it.
_POOL_ZONE = {"notulen-gpu": "zone-2", "notulen-gpu-z1": "zone-1"}

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
_JOB_ID = "00000000-1111-4222-8333-444444444444"


def _posted_pod_specs(monkeypatch) -> tuple[dict[str, Any], dict[str, Any]]:
    """(the Job's pod spec, the placeholder's pod spec), as posted."""
    posted: dict[str, Any] = {}
    monkeypatch.setattr(
        client.BatchV1Api, "create_namespaced_job",
        lambda self, namespace=None, body=None, **kwargs: posted.setdefault("job", body),
    )
    monkeypatch.setattr(
        client.CoreV1Api, "create_namespaced_pod",
        lambda self, namespace=None, body=None, **kwargs: posted.setdefault("pod", body),
    )
    monkeypatch.setenv(
        "KUBECONFIG_B64", base64.b64encode(_DEAD_KUBECONFIG.encode()).decode()
    )
    monkeypatch.setenv("GPU_POOL", "notulen-gpu,notulen-gpu-z1")
    monkeypatch.setenv("NOTULEN_WORKER_IMAGE", "registry.example.com/harness/notulen-worker:v1")
    monkeypatch.setattr(ensure_config_module, "_configured", False)
    previous_default = client.Configuration.get_default_copy()
    try:
        create_notulen_job(
            _JOB_ID, "notulen/audio/2026-01-15-call.webm", "Call", "2026-01-15",
            count_recent_jobs=lambda: 0,
        )
        warm_notulen_gpu(_JOB_ID)
        serialise = client.ApiClient().sanitize_for_serialization
        job = serialise(posted["job"])
        return job["spec"]["template"]["spec"], serialise(posted["pod"])["spec"]
    finally:
        client.Configuration.set_default(previous_default)


def _allowed_pools(pod_spec: dict[str, Any]) -> set[str]:
    """Every pool the required node affinity admits (terms ORed)."""
    terms = pod_spec["affinity"]["nodeAffinity"][
        "requiredDuringSchedulingIgnoredDuringExecution"
    ]["nodeSelectorTerms"]
    return {
        pool
        for term in terms
        for expression in term["matchExpressions"]
        if expression["key"] == _POOL_LABEL and expression["operator"] == "In"
        for pool in expression["values"]
    }


def test_a_notulen_gpu_pod_is_never_bound_to_one_zones_gpu_stock(monkeypatch) -> None:
    """Two zones, the notulen pool ranked first, the placeholder in step."""
    job_pod, placeholder_pod = _posted_pod_specs(monkeypatch)

    assert "nodeSelector" not in job_pod, "a single-pool nodeSelector is one zone"
    pools = _allowed_pools(job_pod)
    zones = {_POOL_ZONE.get(pool) for pool in pools}
    assert len(zones - {None}) >= 2, (
        f"pools {sorted(pools)} cover zones {zones}: one zone's GPU stock-out "
        "leaves the meeting waiting for a node that cannot come"
    )

    preferred = job_pod["affinity"]["nodeAffinity"][
        "preferredDuringSchedulingIgnoredDuringExecution"
    ]
    first = max(preferred, key=lambda term: term["weight"])
    assert first["preference"]["matchExpressions"][0]["values"] == ["notulen-gpu"]

    assert _allowed_pools(placeholder_pod) == pools
    assert placeholder_pod["tolerations"] == job_pod["tolerations"]
