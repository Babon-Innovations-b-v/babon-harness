"""Kubernetes GPU Job submission for the notulen worker.

This ``__init__`` is the seam; every file inside is implementation. A thin
wrapper around the official ``kubernetes`` client that submits one notulen
transcription Job per recording and holds a GPU for a meeting that is still
being recorded.

Module map (one public callable per file):

- ``creators/create_notulen_job.py``  submit one transcription Job; owns the
  ``MAX_DAILY_JOBS`` cost ceiling.
- ``creators/warm_notulen_gpu.py``    hold a GPU with a low-priority
  placeholder Pod while a meeting is still recording.
- ``creators/release_notulen_gpu.py`` delete that placeholder again.
- ``creators/notulen_affinity.py``    the pools a notulen GPU pod may land on,
  the first one preferred.
- ``creators/notulen_tolerations.py`` the taints a notulen GPU pod tolerates.
- ``naming/job_name.py``              the Job-name grammar callers rely on to
  find Jobs later.
- ``cluster/cluster.py``              ``cluster()``, the configured-cluster
  accessor: namespace, the 401-retry call wrapper, the security contexts.
- ``cluster/ensure_config.py``        kubeconfig bootstrap, idempotent.
- ``cluster/k8s_call.py``             one-retry-on-401 call wrapper.
- ``cluster/namespace.py``            ``GPU_NAMESPACE``, read at call time.
- ``config/notulen_worker_image.py``  ``NOTULEN_WORKER_IMAGE``.
- ``config/notulen_pool.py``          ``GPU_POOL`` and the pool taint.
- ``config/max_daily_jobs.py``        ``MAX_DAILY_JOBS`` cost ceiling.
- ``security/*``                      hardened container and pod contexts.

FAILURE POLICY: creators and ``cluster()`` are Tier 1. They raise
(RuntimeError on the daily ceiling; the config bootstrap raises when no
source loads; ApiException propagates through the single 401 retry).

Importing this package requires the ``kubernetes`` client. Callers in the
dashboard import lazily inside functions so the dashboard boots without it.
"""

from __future__ import annotations

from .cluster.cluster import ClusterHandle, cluster
from .cluster.ensure_config import ensure_config
from .cluster.k8s_call import k8s_call
from .cluster.namespace import namespace
from .config.max_daily_jobs import max_daily_jobs
from .config.notulen_worker_image import notulen_worker_image
from .creators.create_notulen_job import create_notulen_job
from .creators.release_notulen_gpu import release_notulen_gpu
from .creators.warm_notulen_gpu import warm_notulen_gpu
from .naming.job_name import job_name
from .security.worker_pod_security_context import worker_pod_security_context
from .security.worker_security_context import worker_security_context

__all__ = [
    "ClusterHandle",
    "cluster",
    "create_notulen_job",
    "ensure_config",
    "job_name",
    "k8s_call",
    "max_daily_jobs",
    "namespace",
    "notulen_worker_image",
    "release_notulen_gpu",
    "warm_notulen_gpu",
    "worker_pod_security_context",
    "worker_security_context",
]
