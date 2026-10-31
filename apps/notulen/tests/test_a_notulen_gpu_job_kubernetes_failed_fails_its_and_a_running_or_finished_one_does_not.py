"""A notulen GPU job Kubernetes failed fails its row; a running or finished one does not.

WHAT IT PINS. `failed_job_reasons` in `app/core/sessions/dead_gpu_jobs.py`, the
seam that decides which rows the dead-GPU-job watch flips to `failed`. Reading a
finished Job as failed would fail a meeting whose minutes are being committed;
missing a failed one leaves the row "transcribing" for ever.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From what
Kubernetes reports for a Job killed at its deadline: condition `Failed`, reason
`DeadlineExceeded`, message "Job was active longer than specified deadline".
Beside it, a Job with condition `Complete` and one with no conditions yet, which
is what Kubernetes reports for a finished and a still-running Job. Only the
first may come back.

WHAT IT WAS PROVED AGAINST. Making the watch accept `Complete` as well as
`Failed`, so the finished Job is reported and the exact-mapping assertion trips.
"""
from __future__ import annotations

import os

# A placeholder DSN for anything that resolves one at import. Nothing here
# opens a connection.
os.environ.setdefault("DB_URL", "postgresql://test/none")

from kubernetes.client import (  # noqa: E402
    V1Job,
    V1JobCondition,
    V1JobStatus,
    V1ObjectMeta,
)

from apps.notulen.app.core.sessions.dead_gpu_jobs import (  # noqa: E402
    failed_job_reasons,
)

DEAD = "00000000-0000-4000-8000-00000000dead"
FINISHED = "00000000-0000-4000-8000-00000000d0e5"
RUNNING = "00000000-0000-4000-8000-0000000000a1"


def _job(job_id: str, conditions: list[V1JobCondition] | None) -> V1Job:
    return V1Job(
        metadata=V1ObjectMeta(labels={"app": "notulen-worker", "job-id": job_id}),
        status=V1JobStatus(conditions=conditions),
    )


def test_only_the_job_kubernetes_failed_is_reported_with_its_reason() -> None:
    """The deadline-killed Job comes back with Kubernetes' message; the others do not."""
    jobs = [
        _job(DEAD, [V1JobCondition(
            type="Failed", status="True", reason="DeadlineExceeded",
            message="Job was active longer than specified deadline",
        )]),
        _job(FINISHED, [V1JobCondition(type="Complete", status="True")]),
        _job(RUNNING, None),
    ]
    assert failed_job_reasons(jobs) == {
        DEAD: "Job was active longer than specified deadline",
    }
