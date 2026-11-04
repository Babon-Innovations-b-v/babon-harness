"""A notulen GPU pod may land on exactly the notulen pools, and its manifest

Every check below is one row of CASES under the one test function; a
row that fails fails the test. The sections below are the notes each
check was written with.

must be one the API server will accept.

WHY THIS IS THE MODULE'S TEST. This package builds a Kubernetes Job manifest
and a placeholder Pod manifest and posts them. Everything else it owns (the
image, the env knobs, the security contexts, the name grammar) only matters
because it ends up in one of those manifests. There are two ways a manifest
can be wrong that cost real money or real time:

1. The pod lands on the wrong GPU node, or on no node at all: an unpinned Job
   can wake a cold node in another pool, or wait for a node no pool can give.
2. The API server rejects the manifest with a 422, and the meeting never
   transcribes.

WHERE THE EXPECTED ANSWER COMES FROM. Not from this package. The first half
implements the Kubernetes scheduling predicate (nodeSelector matching, the
taint and toleration rules, extended-resource fit) from the published
definition and runs it against a model cluster: two notulen pools tainted
``workload=notulen``, another GPU pool tainted for a different workload, an
untainted GPU pool, and a CPU pool. The second half checks the manifest against
Kubernetes' own published validation rules (DNS-1123 names, the label regexes,
the quantity grammar, the no-overcommit rule for extended resources), written
out here as regexes rather than asked of a library that shares code with the
client under test.

WHAT IS STUBBED. Only the HTTP POST: the create call is replaced by a recorder
so the manifest can be read instead of sent. The kubeconfig bootstrap (fed a
real kubeconfig pointing at a dead address) and the client's own serialiser
run for real.
"""
from __future__ import annotations

import inspect


# From a gpu job can only land on the pool it is meant for.

import base64


import re


from pathlib import Path


from typing import Any


import pytest


from kubernetes import client


from gpu_jobs import create_notulen_job, warm_notulen_gpu


from gpu_jobs.cluster import ensure_config as ensure_config_module


# ── The cluster, as modelled ────────────────────────────────────────────────
#
# Every GPU node carries the nvidia GPU-operator taint. The two notulen pools
# (one per zone) also taint themselves `workload=notulen` so only notulen
# lands there; another workload's pool is tainted for it; one GPU pool is
# untainted, which is exactly the pool an unpinned GPU pod would wander onto.
_POOL_LABEL = "k8s.scaleway.com/pool-name"


_NVIDIA_TAINT = {"key": "nvidia.com/gpu", "value": "present", "effect": "NoSchedule"}


_POOLS = "notulen-gpu,notulen-gpu-z1"


_IMAGE = "registry.example.com/harness/notulen-worker:v1"


def _gpu_node(pool: str, *, gpus: int, workload: str | None = None) -> dict[str, Any]:
    taints = [_NVIDIA_TAINT]
    if workload is not None:
        taints = taints + [{"key": "workload", "value": workload, "effect": "NoSchedule"}]
    return {"name": pool, "labels": {_POOL_LABEL: pool}, "taints": taints, "gpus": gpus}


CLUSTER = [
    _gpu_node("notulen-gpu", gpus=1, workload="notulen"),
    _gpu_node("notulen-gpu-z1", gpus=1, workload="notulen"),
    _gpu_node("inference-gpu", gpus=1, workload="inference"),
    _gpu_node("general-gpu", gpus=1),
    {"name": "system", "labels": {_POOL_LABEL: "system"}, "taints": [], "gpus": 0},
]


# ── The Kubernetes scheduling predicate, implemented independently ──────────
def _toleration_matches(toleration: dict[str, Any], taint: dict[str, Any]) -> bool:
    """Does one toleration tolerate one taint?

    Straight from the published rule: an empty `effect` matches every effect; an
    empty `key` with operator `Exists` tolerates everything; operator `Exists`
    ignores the value; operator `Equal`: the default when the field is absent , 
    requires the values to match too.
    """
    effect = toleration.get("effect") or ""
    if effect and effect != taint["effect"]:
        return False
    key = toleration.get("key") or ""
    operator = toleration.get("operator") or "Equal"
    if not key:
        return operator == "Exists"
    if key != taint["key"]:
        return False
    if operator == "Exists":
        return True
    return (toleration.get("value") or "") == (taint.get("value") or "")


def _where_it_can_land(pod_spec: dict[str, Any]) -> list[str]:
    """Every node in CLUSTER this pod spec is schedulable on.

    Four predicates and no more: the nodeSelector must be a subset of the
    node's labels, the required node affinity must match (its terms are ORed,
    the expressions inside one term ANDed; only the `In` operator is modelled
    because it is the only one used here), every NoSchedule taint on the node
    must be tolerated, and the pod's GPU request must fit the node's GPU
    capacity. NoExecute and PreferNoSchedule are not modelled because no pool
    here uses them, and preferred affinity only ranks nodes that already fit.
    """
    selector = pod_spec.get("nodeSelector") or {}
    required_terms = (
        ((pod_spec.get("affinity") or {}).get("nodeAffinity") or {})
        .get("requiredDuringSchedulingIgnoredDuringExecution") or {}
    ).get("nodeSelectorTerms")
    tolerations = pod_spec.get("tolerations") or []
    gpus_wanted = sum(
        int(((container.get("resources") or {}).get("requests") or {}).get("nvidia.com/gpu", 0))
        for container in pod_spec["containers"]
    )

    landing = []
    for node in CLUSTER:
        if any(node["labels"].get(key) != value for key, value in selector.items()):
            continue
        if required_terms is not None and not any(
            all(
                expression["operator"] == "In"
                and node["labels"].get(expression["key"]) in expression["values"]
                for expression in term.get("matchExpressions") or []
            )
            for term in required_terms
        ):
            continue
        blocked = any(
            taint["effect"] == "NoSchedule"
            and not any(_toleration_matches(tol, taint) for tol in tolerations)
            for taint in node["taints"]
        )
        if blocked:
            continue
        if gpus_wanted > node["gpus"]:
            continue
        landing.append(node["name"])
    return landing


# ── Kubernetes API-server validation, implemented independently ─────────────
# A DNS-1123 subdomain, which is what an object name must be.
_DNS_1123_SUBDOMAIN = re.compile(
    r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*$"
)


# A label value. Also the cap on a Job name, because the Job controller stamps
# that name into a `job-name` label on every pod it creates.
_LABEL_VALUE = re.compile(r"^(([A-Za-z0-9][-A-Za-z0-9_.]*)?[A-Za-z0-9])?$")


# The name half of a label key; an optional DNS-subdomain prefix may precede "/".
_LABEL_KEY_NAME = re.compile(r"^[A-Za-z0-9]([-A-Za-z0-9_.]*[A-Za-z0-9])?$")


# resource.Quantity: <signedNumber><suffix>, suffix binary SI, decimal SI or exponent.
_QUANTITY = re.compile(
    r"^[+-]?(\d+(\.\d*)?|\.\d+)((Ki|Mi|Gi|Ti|Pi|Ei)|([eE][+-]?\d+)|[mkMGTPE])?$"
)


def _label_key_is_valid(key: str) -> bool:
    prefix, _, name = key.rpartition("/")
    if prefix and not (_DNS_1123_SUBDOMAIN.match(prefix) and len(prefix) <= 253):
        return False
    return bool(_LABEL_KEY_NAME.match(name)) and len(name) <= 63


# ── Driving the real creators and reading back the real manifest ────────────
# A kubeconfig that parses and points nowhere. The bootstrap in `ensure_config`
# runs for real against it; only the POST is intercepted.
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


# A notulen job id is the recording's uuid4, as the dashboard hands it over.
NOTULEN_JOB_ID = "00000000-1111-4222-8333-444444444444"


@pytest.fixture
def submit(monkeypatch):
    """Hand back a function that runs a creator and returns the posted manifest.

    The recorder replaces `create_namespaced_job`, the one call that leaves the
    process. What it captures is a real `V1Job`, serialised with the client's own
    serialiser, so the dict under test is the JSON body the API server would have
    received rather than a hand-copy of it.
    """
    posted: dict[str, Any] = {}

    def recorder(self, namespace=None, body=None, **kwargs):
        posted["job"] = body
        return body

    monkeypatch.setattr(client.BatchV1Api, "create_namespaced_job", recorder)
    monkeypatch.setenv(
        "KUBECONFIG_B64", base64.b64encode(_DEAD_KUBECONFIG.encode()).decode()
    )
    monkeypatch.setenv("GPU_POOL", _POOLS)
    monkeypatch.setenv("NOTULEN_WORKER_IMAGE", _IMAGE)
    # Force the bootstrap to run against the kubeconfig above instead of reusing
    # whatever an earlier test in this process loaded. monkeypatch puts the
    # module's own flag back afterwards.
    monkeypatch.setattr(ensure_config_module, "_configured", False)
    previous_default = client.Configuration.get_default_copy()

    def run(creator, *args, **kwargs) -> dict[str, Any]:
        creator(*args, **kwargs)
        return client.ApiClient().sanitize_for_serialization(posted["job"])

    try:
        yield run
    finally:
        client.Configuration.set_default(previous_default)


def _notulen_manifest(submit) -> dict[str, Any]:
    return submit(
        create_notulen_job,
        NOTULEN_JOB_ID,
        "notulen/audio/2026-01-15-standup.webm",
        "Standup",
        "2026-01-15",
        # The module's own documented injection point for the cost ceiling, not
        # a mock: passing it keeps the ceiling from listing Jobs on a cluster.
        count_recent_jobs=lambda: 0,
    )


# ── Half one: where the pod can land ────────────────────────────────────────
def _the_notulen_job_fits_the_notulen_pools_and_no_other(submit) -> None:
    """Worked out by hand, then checked against the manifest.

    `inference-gpu`, `general-gpu` and `system` are all excluded by the
    required node affinity before taints are even considered. That leaves the
    two notulen pools, and the pod lands on each only if it tolerates both of
    that node's taints: the GPU operator's `nvidia.com/gpu` and the pools' own
    `workload=notulen`. Drop the affinity and the pod can wander onto
    `general-gpu`; drop the workload toleration and both notulen pools are out.
    """
    pod = _notulen_manifest(submit)["spec"]["template"]["spec"]

    assert _where_it_can_land(pod) == ["notulen-gpu", "notulen-gpu-z1"]


# ── Half two: a manifest the API server will accept ─────────────────────────
def _the_manifest_is_one_the_api_server_would_accept(submit) -> None:
    """Checked against Kubernetes' published validation, not against a fixture.

    Four published rules, every one of them breakable by a caller's own id:

    - the Job name is a DNS-1123 subdomain of at most 63 characters (the Job
      controller stamps that name into a `job-name` label on each pod it
      creates, and a label value stops at 63);
    - every label key and value satisfies the label regexes and length caps,
      which is where a raw caller-supplied id lands, unmangled, in `job-id`;
    - every resource quantity parses under the `resource.Quantity` grammar;
    - `nvidia.com/gpu` is an extended resource and may not be overcommitted, so
      its request must equal its limit and be a whole number.
    """
    manifest = _notulen_manifest(submit)

    name = manifest["metadata"]["name"]
    assert _DNS_1123_SUBDOMAIN.match(name), f"{name!r} is not a DNS-1123 subdomain"
    assert len(name) <= 63, f"{name!r} is {len(name)} characters; a pod label stops at 63"

    label_sets = [
        manifest["metadata"].get("labels") or {},
        manifest["spec"]["template"]["metadata"].get("labels") or {},
    ]
    checked_labels = 0
    for labels in label_sets:
        for key, value in labels.items():
            assert _label_key_is_valid(key), f"label key {key!r} is not valid"
            assert _LABEL_VALUE.match(value) and len(value) <= 63, (
                f"label {key}={value!r} would be rejected; a caller's id reaches "
                "this field unmangled"
            )
            checked_labels += 1
    assert checked_labels >= 4, "the labels carrying the caller's id were not reached"

    for container in manifest["spec"]["template"]["spec"]["containers"]:
        limits = container["resources"].get("limits") or {}
        requests = container["resources"].get("requests") or {}
        for quantity in list(limits.values()) + list(requests.values()):
            assert _QUANTITY.match(quantity), f"{quantity!r} is not a valid quantity"
        assert limits["nvidia.com/gpu"] == requests["nvidia.com/gpu"], (
            "an extended resource cannot be overcommitted: request must equal limit"
        )
        assert int(requests["nvidia.com/gpu"]) == 1, (
            "one GPU per worker; more than one never fits a single-card node "
            "and the pod stays Pending"
        )


# ── The placeholder that holds a notulen GPU during a recording ─────────────
# The PriorityClass as the cluster carries it, read from the manifest applied
# by hand, not from this package.
_WARMUP_PRIORITY_MANIFEST = (
    Path(__file__).resolve().parents[4] / "infra/gpu/k8s/priorityclass.yaml"
)


# The cluster autoscaler's default expendable_pods_priority_cutoff: a pod
# below it never brings up a node.
_AUTOSCALER_EXPENDABLE_CUTOFF = -10


def _warmup_manifest(monkeypatch) -> dict[str, Any]:
    posted: dict[str, Any] = {}

    def recorder(self, namespace=None, body=None, **kwargs):
        posted["pod"] = body
        return body

    monkeypatch.setattr(client.CoreV1Api, "create_namespaced_pod", recorder)
    monkeypatch.setenv(
        "KUBECONFIG_B64", base64.b64encode(_DEAD_KUBECONFIG.encode()).decode()
    )
    monkeypatch.setenv("GPU_POOL", _POOLS)
    monkeypatch.setenv("NOTULEN_WORKER_IMAGE", _IMAGE)
    monkeypatch.setattr(ensure_config_module, "_configured", False)
    previous_default = client.Configuration.get_default_copy()
    try:
        warm_notulen_gpu(NOTULEN_JOB_ID)
        return client.ApiClient().sanitize_for_serialization(posted["pod"])
    finally:
        client.Configuration.set_default(previous_default)


def _the_gpu_placeholder_holds_a_node_the_notulen_job_can_take_over(
    monkeypatch,
) -> None:
    """The placeholder is only worth its GPU if the notulen Job can have it.

    Three things, each worked out from outside the package. It must fit the
    two notulen pools and nothing else, by the same predicate as the Job
    above, or it warms a node the Job can never use. Its name must pass the API server's
    DNS-1123 rule, since the caller's uuid lands in it. And its PriorityClass,
    read from the manifest the cluster was given, must sit below the Job's
    default 0, so the Job preempts it, and at or above the autoscaler's
    expendable cutoff, or no node is ever brought up for it.
    """
    import yaml  # noqa: PLC0415

    pod = _warmup_manifest(monkeypatch)

    assert _where_it_can_land(pod["spec"]) == ["notulen-gpu", "notulen-gpu-z1"]

    name = pod["metadata"]["name"]
    assert _DNS_1123_SUBDOMAIN.match(name) and len(name) <= 63, name

    with open(_WARMUP_PRIORITY_MANIFEST, encoding="utf-8") as manifest_file:
        priority_class = yaml.safe_load(manifest_file)
    assert pod["spec"]["priorityClassName"] == priority_class["metadata"]["name"]
    assert _AUTOSCALER_EXPENDABLE_CUTOFF <= priority_class["value"] < 0
    assert priority_class["preemptionPolicy"] == "Never"


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
    *_cases(_the_notulen_job_fits_the_notulen_pools_and_no_other),
    *_cases(_the_manifest_is_one_the_api_server_would_accept),
    *_cases(_the_gpu_placeholder_holds_a_node_the_notulen_job_can_take_over),
]


@pytest.mark.parametrize("scenario, given, uses", CASES)
def test_a_gpu_job_can_only_land_on_the_pool_it_is_meant_for(scenario, given, uses, request):
    """A notulen GPU pod may land on exactly the notulen pools, and its manifest: every row of CASES must hold."""
    for name in uses:
        request.getfixturevalue(name)
    wanted = [name for name, parameter in inspect.signature(scenario).parameters.items()
              if name not in given and parameter.default is parameter.empty]
    scenario(**given, **{name: request.getfixturevalue(name) for name in wanted})
