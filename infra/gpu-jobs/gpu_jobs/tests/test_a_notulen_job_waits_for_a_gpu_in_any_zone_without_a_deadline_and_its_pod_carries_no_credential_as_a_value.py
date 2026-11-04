"""A notulen job waits for a GPU in any zone without a deadline, its run is still capped, and its pod carries no credential as a value.

Every check below is one row of CASES under the one test function; a
row that fails fails the test. The sections below are the notes each
check was written with.

A notulen Job waits for a GPU node for as long as it takes, and its run is
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

A notulen GPU pod may land in more than one zone, so one zone's GPU stock-out
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

A notulen GPU pod gets its credentials by reference to a cluster Secret, so
no credential is readable by someone who can only read pods.

WHAT IT PINS. `gpu_jobs.create_notulen_job`, through its public interface: the
Job manifest it posts. Only the HTTP POST is replaced by a recorder.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The dashboard
that calls it holds the credentials the worker reads (`entrypoints/worker.py`:
DB_URL, ANTHROPIC_API_KEY, HF_TOKEN, S3_ACCESS_KEY, S3_SECRET_KEY) in its own
environment. The test sets each to a sentinel string, so whatever the code
does, a sentinel showing up anywhere in the posted manifest means a credential
was copied into the pod spec. Each must still reach the container, by
`secretKeyRef` on `notulen-worker-secrets`, or the worker runs without it.

WHAT IT WAS PROVED AGAINST. The Anthropic key copied from the environment as a
value.
"""
from __future__ import annotations

import inspect
import pytest


# From a notulen job waits for a gpu without a deadline and its run is still capped.

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


def _a_notulen_job_waits_for_a_gpu_without_a_deadline_and_its_run_is_still_capped(
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

# From a notulen gpu pod is never bound to one zones gpu stock.

from gpu_jobs import create_notulen_job as create_notulen_job_2, warm_notulen_gpu


_POOL_LABEL = "k8s.scaleway.com/pool-name"


# Where each GPU pool lives, as the cluster carries it.
_POOL_ZONE = {"notulen-gpu": "zone-2", "notulen-gpu-z1": "zone-1"}


_DEAD_KUBECONFIG_2 = """apiVersion: v1
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
        "KUBECONFIG_B64", base64.b64encode(_DEAD_KUBECONFIG_2.encode()).decode()
    )
    monkeypatch.setenv("GPU_POOL", "notulen-gpu,notulen-gpu-z1")
    monkeypatch.setenv("NOTULEN_WORKER_IMAGE", "registry.example.com/harness/notulen-worker:v1")
    monkeypatch.setattr(ensure_config_module, "_configured", False)
    previous_default = client.Configuration.get_default_copy()
    try:
        create_notulen_job_2(
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


def _a_notulen_gpu_pod_is_never_bound_to_one_zones_gpu_stock(monkeypatch) -> None:
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

# From a notulen pod carries no credential as a value in its spec.

import json


_DEAD_KUBECONFIG_3 = """apiVersion: v1
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


_SENTINELS = {
    "DB_URL": "postgresql://app:sentinel-app-password@db/app",
    "DB_URL_OPS": "postgresql://ops:sentinel-ops-password@db/ops",
    "ANTHROPIC_API_KEY": "sk-ant-sentinel-anthropic",
    "HF_TOKEN": "hf_sentinel_huggingface",
    "S3_ACCESS_KEY": "SCWSENTINELACCESSKEY",
    "S3_SECRET_KEY": "sentinel-s3-secret-key",
}


# Env name in the pod -> (Secret, key) it must come from.
_EXPECTED_REFS = {
    "DB_URL": ("notulen-worker-secrets", "DB_URL"),
    "ANTHROPIC_API_KEY": ("notulen-worker-secrets", "ANTHROPIC_API_KEY"),
    "HF_TOKEN": ("notulen-worker-secrets", "HF_TOKEN"),
    "S3_ACCESS_KEY": ("notulen-worker-secrets", "S3_ACCESS_KEY"),
    "S3_SECRET_KEY": ("notulen-worker-secrets", "S3_SECRET_KEY"),
}


def _a_notulen_pod_carries_no_credential_as_a_value_in_its_spec(monkeypatch) -> None:
    """No sentinel in the manifest; each credential arrives by secretKeyRef."""
    posted: dict = {}
    monkeypatch.setattr(
        client.BatchV1Api, "create_namespaced_job",
        lambda self, namespace=None, body=None, **kwargs: posted.setdefault("job", body),
    )
    monkeypatch.setenv(
        "KUBECONFIG_B64", base64.b64encode(_DEAD_KUBECONFIG_3.encode()).decode()
    )
    monkeypatch.setenv("NOTULEN_WORKER_IMAGE", "registry.example.com/harness/notulen-worker:v1")
    for name, sentinel in _SENTINELS.items():
        monkeypatch.setenv(name, sentinel)
    monkeypatch.setattr(ensure_config_module, "_configured", False)
    previous_default = client.Configuration.get_default_copy()
    try:
        create_notulen_job(
            "00000000-1111-4222-8333-444444444444",
            "notulen/audio/2026-01-15-call.webm", "Call", "2026-01-15",
            count_recent_jobs=lambda: 0,
        )
        job = client.ApiClient().sanitize_for_serialization(posted["job"])
    finally:
        client.Configuration.set_default(previous_default)

    manifest = json.dumps(job)
    leaked = [name for name, sentinel in _SENTINELS.items() if sentinel in manifest]
    assert not leaked, f"credentials copied into the pod spec as values: {leaked}"

    env = {
        entry["name"]: entry
        for entry in job["spec"]["template"]["spec"]["containers"][0]["env"]
    }
    for name, (secret, key) in _EXPECTED_REFS.items():
        ref = env.get(name, {}).get("valueFrom", {}).get("secretKeyRef", {})
        assert (ref.get("name"), ref.get("key")) == (secret, key), (
            f"{name} must come from Secret {secret!r} key {key!r}, got {env.get(name)}"
        )


def _cases(scenario, argnames="", argvalues=((),), ids=None, *, marks=(), uses=()):
    """One case per row a check is given; a check given no rows is one case of its fixtures."""
    names = [name.strip() for name in argnames.split(",") if name.strip()] if isinstance(argnames, str) else list(argnames)
    rows = []
    for index, row in enumerate(argvalues):
        row_marks, row_id = (), None
        if isinstance(row, type(pytest.param())):
            row, row_marks, row_id = row.values, row.marks, row.id
        elif len(names) == 1:
            row = (row,)
        if row_id is None and isinstance(ids, (list, tuple)):
            row_id = ids[index]
        label = scenario.__name__.lstrip("_") + (f"-{row_id if row_id is not None else index}" if names else "")
        rows.append(pytest.param(scenario, dict(zip(names, row)), tuple(uses), id=label, marks=(*marks, *row_marks)))
    return rows


CASES = [
    *_cases(_a_notulen_job_waits_for_a_gpu_without_a_deadline_and_its_run_is_still_capped),
    *_cases(_a_notulen_gpu_pod_is_never_bound_to_one_zones_gpu_stock),
    *_cases(_a_notulen_pod_carries_no_credential_as_a_value_in_its_spec),
]


@pytest.mark.parametrize("scenario, given, uses", CASES)
def test_a_notulen_job_waits_for_a_gpu_in_any_zone_without_a_deadline_and_its_pod_carries_no_credential_as_a_value(scenario, given, uses, request):
    """A notulen job waits for a GPU in any zone without a deadline, its run is still capped, and its pod carries no credential as a value: every row of CASES must hold."""
    for name in uses:
        request.getfixturevalue(name)
    wanted = [name for name, parameter in inspect.signature(scenario).parameters.items()
              if name not in given and parameter.default is parameter.empty]
    scenario(**given, **{name: request.getfixturevalue(name) for name in wanted})
