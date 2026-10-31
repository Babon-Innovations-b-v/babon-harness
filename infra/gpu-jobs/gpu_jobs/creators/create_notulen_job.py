"""Submit one notulen GPU transcription Job.

Owns the Job manifest and the daily cost ceiling. What is NOT here: dispatch
policy (when to fire, the CPU fallback, retry), which lives with the caller,
``apps/notulen/app/core/minutes/gpu_dispatch.py``.

Credentials reach the pod only by reference: every secret comes from the
``notulen-worker-secrets`` Secret by ``secretKeyRef``, and the non-secret
settings from the ``notulen-worker-config`` ConfigMap. Onboarding creates
both (``infra/gpu/k8s/``). A value in the pod spec would be readable by
anyone who can read pods.

FAILURE POLICY: Tier 1. Raises RuntimeError when the daily Job ceiling is
reached; ApiException propagates (through the single 401 retry). The
dashboard catches and falls back to CPU; that decision is the caller's,
never made silently here.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from kubernetes import client

from ..cluster.ensure_config import ensure_config
from ..cluster.k8s_call import k8s_call
from ..cluster.namespace import namespace
from ..config.max_daily_jobs import max_daily_jobs
from ..config.notulen_worker_image import notulen_worker_image
from ..naming.job_name import job_name
from ..security.worker_pod_security_context import worker_pod_security_context
from ..security.worker_security_context import worker_security_context
from .notulen_affinity import notulen_affinity
from .notulen_tolerations import notulen_tolerations

log = logging.getLogger(__name__)

#: The Secret only the notulen pod reads. Created by onboarding from the vault.
NOTULEN_WORKER_SECRET = "notulen-worker-secrets"
#: The ConfigMap with the worker's non-secret settings (S3 location, language).
NOTULEN_WORKER_CONFIG = "notulen-worker-config"
#: The image pull Secret for the private container registry.
REGISTRY_PULL_SECRET = "registry-pull"

#: Env name in the pod -> (key in the Secret, required).
_SECRET_ENV = {
    "DB_URL": ("DB_URL", True),
    "ANTHROPIC_API_KEY": ("ANTHROPIC_API_KEY", True),
    "S3_ACCESS_KEY": ("S3_ACCESS_KEY", True),
    "S3_SECRET_KEY": ("S3_SECRET_KEY", True),
    # Optional: without it the worker skips diarization (no speaker labels).
    "HF_TOKEN": ("HF_TOKEN", False),
}

APP_LABEL = "notulen-worker"


def _secret_env(name: str, key: str, required: bool) -> client.V1EnvVar:
    """An env var read from one key of the notulen worker Secret."""
    return client.V1EnvVar(
        name=name,
        value_from=client.V1EnvVarSource(
            secret_key_ref=client.V1SecretKeySelector(
                name=NOTULEN_WORKER_SECRET, key=key, optional=not required,
            ),
        ),
    )


def _count_recent_jobs() -> int:
    """Count notulen Jobs created in the last 24 h (cost-ceiling input)."""
    api = client.BatchV1Api()
    jobs = api.list_namespaced_job(
        namespace=namespace(), label_selector=f"app={APP_LABEL}",
    )
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    return sum(
        1
        for recent_job in jobs.items
        if recent_job.metadata.creation_timestamp
        and recent_job.metadata.creation_timestamp > cutoff
    )


def create_notulen_job(
    job_id: str,
    audio_key: str,
    title: str,
    meeting_date: str,
    attendees: str = "",
    agenda: str = "",
    *,
    count_recent_jobs: Callable[[], int] = _count_recent_jobs,
) -> str:
    """Create a GPU Job that processes one recording end to end.

    The worker downloads the audio from S3, runs pyannote diarization and
    whisper-large-v3 on the GPU, writes the minutes with Claude, and parks
    them in PostgreSQL as ``committing`` for the dashboard to commit.

    ``count_recent_jobs`` is the injectable cost-ceiling collaborator, so a
    test can pin the ceiling without a cluster.

    Returns the Job name.
    """
    ensure_config()
    job_namespace = namespace()

    max_daily = max_daily_jobs()
    if count_recent_jobs() >= max_daily:
        raise RuntimeError(
            f"Daily job limit reached (>={max_daily}). "
            f"Increase MAX_DAILY_JOBS if needed."
        )

    name = job_name("notulen", job_id, seed_chars=20)

    env_vars = [
        client.V1EnvVar(name="JOB_ID", value=job_id),
        client.V1EnvVar(name="AUDIO_KEY", value=audio_key),
        client.V1EnvVar(name="TITLE", value=title),
        client.V1EnvVar(name="MEETING_DATE", value=meeting_date),
        client.V1EnvVar(name="ATTENDEES", value=attendees or ""),
        client.V1EnvVar(name="AGENDA", value=agenda or ""),
        # The pod runs as uid 1000, whose HOME would default to `/`, which it
        # cannot write. /tmp gives the model caches a writable root.
        client.V1EnvVar(name="HOME", value="/tmp"),
    ]
    env_vars.extend(
        _secret_env(env_name, key, required)
        for env_name, (key, required) in _SECRET_ENV.items()
    )

    container = client.V1Container(
        name="notulen-worker",
        image=notulen_worker_image(),
        image_pull_policy="IfNotPresent",
        security_context=worker_security_context(),
        resources=client.V1ResourceRequirements(
            limits={"nvidia.com/gpu": "1"},
            requests={"nvidia.com/gpu": "1", "memory": "8Gi", "cpu": "2"},
        ),
        env=env_vars,
        env_from=[
            client.V1EnvFromSource(
                config_map_ref=client.V1ConfigMapEnvSource(name=NOTULEN_WORKER_CONFIG),
            ),
        ],
    )

    pod_spec = client.V1PodSpec(
        containers=[container],
        restart_policy="Never",
        image_pull_secrets=[client.V1LocalObjectReference(name=REGISTRY_PULL_SECRET)],
        security_context=worker_pod_security_context(),
        # 4 h cap on the transcription itself. A pod's activeDeadlineSeconds
        # counts from the moment the kubelet on its node accepts it, so the
        # wait for a GPU node is not counted: the Job waits for a GPU for as
        # long as it takes, and a running worker that hangs is still stopped.
        active_deadline_seconds=14400,
        # One of the notulen pools, the first preferred (config/notulen_pool.py).
        affinity=notulen_affinity(),
        tolerations=notulen_tolerations(),
    )

    job = client.V1Job(
        api_version="batch/v1",
        kind="Job",
        metadata=client.V1ObjectMeta(
            name=name,
            namespace=job_namespace,
            labels={"app": APP_LABEL, "job-id": job_id},
        ),
        spec=client.V1JobSpec(
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(
                    labels={"app": APP_LABEL, "job-id": job_id},
                ),
                spec=pod_spec,
            ),
            backoff_limit=0,
            # No Job-level activeDeadlineSeconds. A Job's deadline counts the
            # wait for a GPU node, so a meeting that waited out a stock-out
            # would be killed still Pending. The run cap sits on the pod.
            ttl_seconds_after_finished=300,  # clean up 5 min after done
        ),
    )

    api = client.BatchV1Api()
    k8s_call(api.create_namespaced_job, namespace=job_namespace, body=job)
    log.info("Created notulen Job %s for job %s", name, job_id)
    return name
