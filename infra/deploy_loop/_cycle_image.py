"""The deploy-cycle image rolls itself: what is baked in, when to build, and the trial.

OWNS: three answers about the image the deploy loop runs in.

  1. What the image bakes in, as one sum (`baked_sum`): every file the
     Dockerfile copies plus the Dockerfile itself, leaving out what never runs
     (any `tests/` directory, `__pycache__`, markdown). Two trees with one sum
     build the same image.
  2. Whether the cycle should build one now (`build_decision`): only when the
     shipped tree's sum is neither the image in use nor the one on trial, and
     not one the guard refused within the retry window.
  3. The trial (`judge_trial`): a new image runs only the `deploy-cycle`
     CronJob until one cycle Job in it ends green; then every object naming the
     image moves to it. Failed cycle Jobs in it, or no green one in time, put
     the CronJob back on the image every other object still runs. The
     guard CronJob that asks this runs the old image all the while, so a loop
     image too broken to start a cycle is still rolled back.

DOES NOT OWN: the kubectl calls (`run_guard` makes them through the `kubectl`
callable it is given; `infra/auto-deploy/steps/cluster.sh` builds, smoke-tests
and starts a trial).

THE STATE is ConfigMap `deploy-cycle-image` in namespace deploy, keys:
`good` (the image every object runs), `good_sum`, `candidate`,
`candidate_sum`, `candidate_since` (epoch seconds), `refused_image`,
`refused_sum`, `refused_at`. A missing key reads as empty.
"""
from __future__ import annotations

import calendar
import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ._pins import repository

#: The repository paths `image/Dockerfile` COPYs; its own directory is inside.
BAKED = ("infra/deploy_loop",)
#: The CronJob a new image is tried on first.
TRIAL_CRONJOB = "deploy-cycle"
#: The env var every object naming the image carries for the gate Jobs.
IMAGE_ENV = "DEPLOY_CYCLE_IMAGE"
STATE_KEYS = ("good", "good_sum", "candidate", "candidate_sum", "candidate_since",
              "refused_image", "refused_sum", "refused_at")


def _runs(relative: Path) -> bool:
    """False for a file the image never runs: tests, bytecode, markdown."""
    parts = relative.parts
    return "tests" not in parts and "__pycache__" not in parts and relative.suffix != ".md"


def baked_files(root: Path) -> list:
    """Every baked file under `root` that runs, as sorted repository paths."""
    found = []
    for baked in BAKED:
        path = root / baked
        if path.is_file():
            candidates = [path]
        elif path.is_dir():
            candidates = [entry for entry in path.rglob("*") if entry.is_file()]
        else:
            candidates = []
        for entry in candidates:
            relative = entry.relative_to(root)
            if _runs(relative):
                found.append(relative.as_posix())
    return sorted(found)


def baked_sum(root: Path) -> str:
    """16 hex of sha256 over each running baked file's path and content."""
    digest = hashlib.sha256()
    for relative in baked_files(root):
        digest.update(relative.encode() + b"\0")
        digest.update(hashlib.sha256((root / relative).read_bytes()).digest())
    return digest.hexdigest()[:16]


def _number(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def build_decision(state: dict, tree_sum: str, now: float, retry_seconds: float) -> tuple:
    """(`build` | `current` | `trial` | `refused`, why) for a tree whose baked sum is `tree_sum`."""
    if state.get("candidate"):
        return "trial", f"{state['candidate']} is on trial; nothing new is built until it ends"
    if tree_sum and tree_sum == state.get("good_sum"):
        return "current", f"{state.get('good')} already carries this tree's baked files"
    if tree_sum and tree_sum == state.get("refused_sum") \
            and now - _number(state.get("refused_at", "")) < retry_seconds:
        return "refused", f"{state.get('refused_image')} with these baked files was rolled back; tried again after {int(retry_seconds)} s"
    return "build", "the baked files differ from the image in use"


@dataclass(frozen=True)
class Verdict:
    """What the guard does now: the action, the image it concerns, and why."""

    action: str
    image: str
    reason: str


def _job_image(job: dict) -> str:
    spec = (((job.get("spec") or {}).get("template") or {}).get("spec") or {})
    containers = spec.get("containers") or [{}]
    return str(containers[0].get("image", ""))


def _job_condition(job: dict) -> str:
    status = job.get("status") or {}
    for condition in status.get("conditions") or []:
        if condition.get("status") == "True" and condition.get("type") in ("Complete", "Failed"):
            return condition["type"]
    return ""


def _epoch(timestamp: str) -> float:
    try:
        return float(calendar.timegm(time.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")))
    except (TypeError, ValueError):
        return 0.0


def judge_trial(state: dict, cycle_image: str, jobs: list, now: float,
                failures: int = 2, seconds: float = 1800) -> Verdict:
    """The guard's one decision, from the state, the CronJob's image and its Jobs.

    `jobs` are the deploy-cycle Jobs (kubectl JSON items). A Job counts for the
    trial when it runs the candidate and started at or after the trial did.
    """
    good, candidate = state.get("good", ""), state.get("candidate", "")
    if not cycle_image:
        return Verdict("wait", "", "the deploy-cycle CronJob names no image")
    if not good:
        return Verdict("seed", cycle_image, "no good image recorded; the one the cycle runs is it")
    if candidate and cycle_image != candidate:
        if cycle_image == good:
            return Verdict("withdraw", candidate, "the CronJob is back on the good image; the trial is over")
        return Verdict("adopt", cycle_image, "the CronJob was set to an image nobody tried; it is the trial now")
    if not candidate:
        if cycle_image != good:
            return Verdict("adopt", cycle_image, "the CronJob was set to an image nobody tried; it is the trial now")
        return Verdict("heal", good, "no trial; every object runs the good image")
    since = _number(state.get("candidate_since", ""))
    tried = [job for job in jobs if _job_image(job) == candidate
             and _epoch(str((job.get("metadata") or {}).get("creationTimestamp", ""))) >= since - 1]
    ends = [_job_condition(job) for job in tried]
    if "Complete" in ends:
        return Verdict("promote", candidate, "a cycle in it ended green")
    if ends.count("Failed") >= failures:
        return Verdict("roll-back", candidate, f"{ends.count('Failed')} cycles in it failed")
    if now - since > seconds:
        return Verdict("roll-back", candidate, f"no cycle in it ended green within {int(seconds)} s")
    return Verdict("wait", candidate, f"{len(tried)} cycle(s) in it so far, none green yet")


def _pod_spec(item: dict) -> dict:
    spec = item.get("spec") or {}
    if item.get("kind") == "CronJob":
        spec = (spec.get("jobTemplate") or {}).get("spec") or {}
    return ((spec.get("template") or {}).get("spec")) or {}


def pin_patches(documents: list, image: str, only: str = "", skip: str = "") -> list:
    """`(kind, name, strategic merge patch)` moving every reference onto `image`.

    A reference is a container or init container of `image`'s repository, or
    an `IMAGE_ENV` value of it. `only`/`skip` name one `kind/name`
    (lowercase kind). An object already on `image` everywhere gets no patch.
    """
    wanted = repository(image)
    patches = []
    for document in documents:
        items = document.get("items") if str(document.get("kind", "")).endswith("List") else [document]
        for item in items or []:
            key = f"{str(item.get('kind', '')).lower()}/{(item.get('metadata') or {}).get('name', '')}"
            if (only and key != only) or (skip and key == skip):
                continue
            pod = _pod_spec(item)
            moved = {}
            for field in ("initContainers", "containers"):
                for container in pod.get(field) or []:
                    change = {}
                    current = str(container.get("image", ""))
                    if current != image and repository(current) == wanted:
                        change["image"] = image
                    env = [entry for entry in container.get("env") or []
                           if entry.get("name") == IMAGE_ENV and "value" in entry and entry["value"] != image]
                    if env:
                        change["env"] = [{"name": IMAGE_ENV, "value": image}]
                    if change:
                        moved.setdefault(field, []).append({"name": container.get("name"), **change})
            if not moved:
                continue
            patch = {"spec": {"template": {"spec": moved}}}
            if item.get("kind") == "CronJob":
                patch = {"spec": {"jobTemplate": patch}}
            patches.append((str(item["kind"]).lower(), key.split("/", 1)[1], json.dumps(patch, sort_keys=True)))
    return patches


#: kubectl(argv) -> (rc, stdout). argv starts after `kubectl -n <namespace>`.
Kubectl = Callable[[list], tuple]


def _json(kubectl: Kubectl, argv: list) -> dict:
    rc, out = kubectl(argv)
    if rc != 0:
        raise RuntimeError(f"kubectl {' '.join(argv)} failed: {out.strip()[:300]}")
    return json.loads(out)


def _pin(kubectl: Kubectl, documents: list, image: str, only: str = "", skip: str = "") -> list:
    """Apply `pin_patches`; returns the objects kubectl refused."""
    refused = []
    for kind, name, patch in pin_patches(documents, image, only=only, skip=skip):
        rc, out = kubectl(["patch", kind, name, "--type", "strategic", "-p", patch])
        print(f"[cycle-image] {kind}/{name} -> {image}" if rc == 0 else
              f"[cycle-image] kubectl refused {image} on {kind}/{name}: {out.strip()[:200]}")
        if rc != 0:
            refused.append(f"{kind}/{name}")
    return refused


def _write_state(kubectl: Kubectl, configmap: str, fields: dict) -> None:
    rc, out = kubectl(["patch", "configmap", configmap, "--type", "merge", "-p", json.dumps({"data": fields})])
    if rc != 0:
        raise RuntimeError(f"could not write configmap {configmap}: {out.strip()[:300]}")


def run_guard(kubectl: Kubectl, configmap: str = "deploy-cycle-image", now: float | None = None,
              failures: int = 2, seconds: float = 1800) -> int:
    """One guard tick: read, judge, act. 0 done, 1 something could not be read or written."""
    now = time.time() if now is None else now
    try:
        state = {key: str(value) for key, value in
                 (_json(kubectl, ["get", "configmap", configmap, "-o", "json"]).get("data") or {}).items()}
        listing = _json(kubectl, ["get", "cronjobs,deployments,daemonsets", "-o", "json"])
        jobs = _json(kubectl, ["get", "jobs", "-l", f"app.kubernetes.io/name={TRIAL_CRONJOB}", "-o", "json"])
    except (RuntimeError, ValueError) as error:
        print(f"[cycle-image] guard could not read the cluster: {error}")
        return 1
    trial = f"cronjob/{TRIAL_CRONJOB}"
    cycle = [item for item in listing.get("items") or []
             if item.get("kind") == "CronJob" and (item.get("metadata") or {}).get("name") == TRIAL_CRONJOB]
    containers = _pod_spec(cycle[0]).get("containers") if cycle else []
    cycle_image = str((containers or [{}])[0].get("image", ""))
    verdict = judge_trial(state, cycle_image, jobs.get("items") or [], now, failures, seconds)
    print(f"[cycle-image] {verdict.action} {verdict.image or '-'}: {verdict.reason}")
    blank = {"candidate": "", "candidate_sum": "", "candidate_since": ""}
    try:
        if verdict.action == "seed":
            _write_state(kubectl, configmap, {"good": verdict.image})
        elif verdict.action == "adopt":
            _write_state(kubectl, configmap, {"candidate": verdict.image, "candidate_sum": "",
                                              "candidate_since": str(int(now))})
        elif verdict.action == "withdraw":
            _write_state(kubectl, configmap, blank)
        elif verdict.action == "promote":
            _write_state(kubectl, configmap, {**blank, "good": verdict.image,
                                              "good_sum": state.get("candidate_sum", "")})
            state["good"] = verdict.image
        elif verdict.action == "roll-back":
            if _pin(kubectl, [listing], state["good"], only=trial):
                return 1
            _write_state(kubectl, configmap, {**blank, "refused_image": verdict.image,
                                              "refused_sum": state.get("candidate_sum", ""),
                                              "refused_at": str(int(now))})
    except RuntimeError as error:
        print(f"[cycle-image] {error}")
        return 1
    good = state.get("good") or (verdict.image if verdict.action == "seed" else "")
    if not good:
        return 0
    # Everything but the CronJob on trial runs the good image: this is the
    # promotion, and it heals an object a hand applied from an older pin.
    on_trial = verdict.action in ("adopt", "wait", "roll-back")
    refused = _pin(kubectl, [listing], good, skip=trial if on_trial else "")
    return 1 if refused else 0
