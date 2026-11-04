"""Read a finished gate Job the way steps/40-gate.sh reads pytest's own exit code.

OWNS: the one mapping from a Kubernetes Job (and the pod it ran) to the exit
code the step already classifies. The step keeps classifying, so red, amber,
the three-amber escalation, the verdict cache and the eject keep the meaning
they had when pytest ran on one server.

THE TABLE, in the order it is asked:

    the Job failed with reason DeadlineExceeded ..... 124  (timeout, AMBER)
    the cluster ended the pod (evicted, preempted) .. 125  (could not finish, AMBER)
    the fetch (init container) failed ............... 125  (could not start, AMBER)
    the run image does not exist and the gated
      commit is the one that changed the pin ........ 4    (the commit's, RED)
    a container stuck on an image or config error ... 125  (could not start, AMBER)
    the run container was OOMKilled ................. 137  (AMBER)
    the run container exited with N ................. N    (pytest's own code)
    the pod failed with no container answer ......... 125
    the Job completed ............................... 0
    the Job failed with no pod left to ask .......... 125
    the caller's own deadline passed ................ 124
    otherwise ....................................... None (still running)

The deadline is asked FIRST: a container the deadline killed exits with
whatever SIGTERM gives it, and that number must never be read as the suite's.
Never map a fault of the Job to 0 to 5: those are pytest's answers, and 1 is
the one the eject acts on.

FAILURE POLICY: pure; a document missing a field is read as "not there".
"""
from __future__ import annotations

RC_TIMEOUT = 124
RC_COULD_NOT_START = 125
RC_OOM = 137
#: pytest's usage error: red, the commit's own.
RC_PIN_MISSING = 4

#: Waiting reasons that never resolve on their own inside one cycle.
_START_FAILURES = frozenset(
    {"ErrImagePull", "ImagePullBackOff", "InvalidImageName", "CreateContainerConfigError", "CreateContainerError"}
)
#: Pod reasons the cluster gives when IT ended the pod.
_POD_LOST = frozenset({"Evicted", "Preempting", "NodeLost", "Shutdown", "Terminated", "NodeAffinity"})
#: What a registry says, through the kubelet, about a reference it does not hold.
_NOT_THERE = ("not found", "manifest unknown", "no such manifest")


def _true_conditions(job: dict) -> dict:
    conditions = (job.get("status") or {}).get("conditions") or []
    return {condition.get("type"): condition for condition in conditions if condition.get("status") == "True"}


def _newest_pod(pods: list) -> dict | None:
    if not pods:
        return None
    return max(pods, key=lambda pod: (pod.get("metadata") or {}).get("creationTimestamp") or "")


def _init_answer(status: dict) -> int | None:
    for init in status.get("initContainerStatuses") or []:
        state = init.get("state") or {}
        terminated = state.get("terminated")
        if terminated and int(terminated.get("exitCode", 0)) != 0:
            return RC_COULD_NOT_START
        waiting = state.get("waiting")
        if waiting and waiting.get("reason") in _START_FAILURES:
            return RC_COULD_NOT_START
    return None


def _image_missing(status: dict) -> bool:
    for container in status.get("containerStatuses") or []:
        waiting = (container.get("state") or {}).get("waiting") or {}
        message = (waiting.get("message") or "").lower()
        if waiting.get("reason") in ("ErrImagePull", "ImagePullBackOff") and any(
            words in message for words in _NOT_THERE
        ):
            return True
    return False


def _run_answer(status: dict) -> int | None:
    for container in status.get("containerStatuses") or []:
        state = container.get("state") or {}
        terminated = state.get("terminated")
        if terminated:
            if terminated.get("reason") == "OOMKilled":
                return RC_OOM
            return int(terminated.get("exitCode", RC_COULD_NOT_START))
        waiting = state.get("waiting")
        if waiting and waiting.get("reason") in _START_FAILURES:
            return RC_COULD_NOT_START
    return None


def gate_job_outcome(job: dict, pods: list, timed_out: bool, pin_is_new: bool = False) -> int | None:
    """The exit code this Job stands for, or None while it is still running.

    `pin_is_new`: the gated commit is the one that changed infra/gate-image/pin.
    """
    conditions = _true_conditions(job or {})
    failed = conditions.get("Failed")
    if failed is not None and failed.get("reason") == "DeadlineExceeded":
        return RC_TIMEOUT
    pod = _newest_pod(pods or [])
    if pod is not None:
        status = pod.get("status") or {}
        if status.get("reason") in _POD_LOST:
            return RC_COULD_NOT_START
        answer = _init_answer(status)
        if answer is not None:
            return answer
        if pin_is_new and _image_missing(status):
            return RC_PIN_MISSING
        answer = _run_answer(status)
        if answer is not None:
            return answer
        if status.get("phase") == "Failed":
            return RC_COULD_NOT_START
    if "Complete" in conditions:
        return 0
    if failed is not None:
        return RC_COULD_NOT_START
    if timed_out:
        return RC_TIMEOUT
    return None
