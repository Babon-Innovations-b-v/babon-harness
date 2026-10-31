"""Hold a notulen GPU for a meeting that is still being recorded.

A cloud GPU node can take half an hour or more to power on when the zone is
short of cards, and the notulen Job only asks for its GPU once the meeting
has ended. This submits a placeholder Pod the moment a recording starts, so
the wait happens during the meeting: the autoscaler brings up a node in one
of the notulen pools, the node pulls the worker image, and the Pod then
sleeps on the GPU.

The placeholder runs at the ``notulen-gpu-warmup`` PriorityClass (below the
default 0, never preempting), so the real notulen Job takes its place by
preemption whenever it arrives. A bare Pod, not a Job: a preempted Job counts
as failed, and the dead-job watch would page on it.

FAILURE POLICY: Tier 1, ApiException propagates (through the single 401
retry), except 409: a placeholder for this key already exists, which is the
warm-up already doing its job. The caller decides that a failed warm-up
must never cost a recording.
"""

from __future__ import annotations

from kubernetes import client
from kubernetes.client.exceptions import ApiException

from ..cluster.ensure_config import ensure_config
from ..cluster.k8s_call import k8s_call
from ..cluster.namespace import namespace
from ..config.notulen_worker_image import notulen_worker_image
from ..naming.job_name import job_name
from .create_notulen_job import REGISTRY_PULL_SECRET
from ..security.worker_pod_security_context import worker_pod_security_context
from ..security.worker_security_context import worker_security_context
from .notulen_affinity import notulen_affinity
from .notulen_tolerations import notulen_tolerations

# Cluster object, applied once from infra/gpu/k8s/priorityclass.yaml.
WARMUP_PRIORITY_CLASS = "notulen-gpu-warmup"
WARMUP_APP_LABEL = "notulen-gpu-warmup"

# The dashboard retires a forgotten recording after 6 h
# (core/sessions/stale_cleanup.py), so no real meeting outlives this, and a
# placeholder whose release was missed costs at most 6 h of one GPU.
WARMUP_LIFETIME_SECONDS = 6 * 3600


def warm_notulen_gpu_name(key: str) -> str:
    """The placeholder Pod name for one recording key."""
    return job_name("notulen-warmup", key, seed_chars=20)


def warm_notulen_gpu(key: str) -> str:
    """Submit the placeholder Pod for one recording; returns its name.

    ``key`` names the recording: the notulen job id.
    """
    ensure_config()
    pod_name = warm_notulen_gpu_name(key)

    container = client.V1Container(
        name="notulen-gpu-warmup",
        # The worker's own image, so the node has it cached when the Job lands.
        image=notulen_worker_image(),
        image_pull_policy="IfNotPresent",
        command=["sleep", str(WARMUP_LIFETIME_SECONDS)],
        security_context=worker_security_context(),
        resources=client.V1ResourceRequirements(
            limits={"nvidia.com/gpu": "1"},
            requests={"nvidia.com/gpu": "1", "memory": "64Mi", "cpu": "50m"},
        ),
    )
    pod = client.V1Pod(
        api_version="v1",
        kind="Pod",
        metadata=client.V1ObjectMeta(
            name=pod_name,
            namespace=namespace(),
            labels={"app": WARMUP_APP_LABEL},
        ),
        spec=client.V1PodSpec(
            containers=[container],
            restart_policy="Never",
            priority_class_name=WARMUP_PRIORITY_CLASS,
            active_deadline_seconds=WARMUP_LIFETIME_SECONDS,
            termination_grace_period_seconds=0,
            image_pull_secrets=[client.V1LocalObjectReference(name=REGISTRY_PULL_SECRET)],
            security_context=worker_pod_security_context(),
            # The same pools and tolerations as the notulen Job: warming any
            # other pool would buy a node the Job can never use.
            affinity=notulen_affinity(),
            tolerations=notulen_tolerations(),
        ),
    )

    try:
        k8s_call(client.CoreV1Api().create_namespaced_pod, namespace=namespace(), body=pod)
    except ApiException as exc:
        if exc.status != 409:
            raise
    return pod_name
