"""The deploy loop's cluster half: what the cycle asks Kubernetes, as pure functions.

Tier S, standard library only: the cycle runs `python3 -m infra.deploy_loop
<verb>` with the cycle image's system python, before any venv exists. Module map:

    _receiver.py  the push receiver: the HMAC and branch check, and which CronJobs a push starts
    _gate_job.py  the Job one gate run is: the gated commit's own gate image, a clone of its own
    _outcome.py   a finished gate Job and its pod, read as the exit code steps/40-gate.sh classifies
    _bookmark.py  what ConfigMap deploy-bookmark may hold
    _pins.py      which objects run another tag of an image the cycle just built
    _images.py    the stack's own images: which compose service builds each, from which Dockerfile
    _shards.py    one gate run as one Job per module group, and the code their answers add up to
    _trust.py     the newest commit the lane's verdicts let the cycle ship without testing again
    _cycle_image.py  the deploy-cycle image rolling itself: its baked sum, when to build, the trial
    __main__.py   the verbs the steps call; the only file here that runs kubectl

Bash callers: `infra/auto-deploy/steps/cluster.sh`. Manifests: `infra/k8s/deploy/`.
"""
from __future__ import annotations

from ._bookmark import bookmark_sha
from ._cycle_image import baked_sum, build_decision, judge_trial, pin_patches, run_guard
from ._gate_job import gate_job_manifest, pinned_gate_image
from ._images import stack_images
from ._outcome import gate_job_outcome
from ._pins import image_targets
from ._receiver import cronjobs_to_start, push_should_trigger
from ._shards import combined_rc, read_shards
from ._trust import trusted_head

__all__ = [
    "baked_sum",
    "bookmark_sha",
    "build_decision",
    "combined_rc",
    "cronjobs_to_start",
    "gate_job_manifest",
    "gate_job_outcome",
    "image_targets",
    "judge_trial",
    "pin_patches",
    "pinned_gate_image",
    "push_should_trigger",
    "read_shards",
    "run_guard",
    "stack_images",
    "trusted_head",
]
