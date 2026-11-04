"""The deploy loop's cluster half: what the cycle asks Kubernetes, as pure functions.

Tier S, standard library only: the cycle runs `python3 -m infra.deploy_loop
<verb>` with the cycle image's system python, before any venv exists. Module map:

    _receiver.py  the push receiver: the HMAC and branch check, and which CronJobs a push starts
    _gate_job.py  the Job one gate run is: the gated commit's own gate image, a clone of its own
    _outcome.py   a finished gate Job and its pod, read as the exit code steps/40-gate.sh classifies
    _bookmark.py  what ConfigMap deploy-bookmark may hold
    _pins.py      which objects run another tag of an image the cycle just built
    _images.py    the stack's own images: which compose service builds each, from which Dockerfile
    __main__.py   the verbs the steps call; the only file here that runs kubectl

Bash callers: `infra/auto-deploy/steps/cluster.sh`. Manifests: `infra/k8s/deploy/`.
"""
from __future__ import annotations

from ._bookmark import bookmark_sha
from ._gate_job import gate_job_manifest, pinned_gate_image
from ._images import stack_images
from ._outcome import gate_job_outcome
from ._pins import image_targets
from ._receiver import cronjobs_to_start, push_should_trigger

__all__ = [
    "bookmark_sha",
    "cronjobs_to_start",
    "gate_job_manifest",
    "gate_job_outcome",
    "image_targets",
    "pinned_gate_image",
    "push_should_trigger",
    "stack_images",
]
