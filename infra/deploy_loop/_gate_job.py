"""The Job one gate run is: the gated commit's own gate image, and a clone of its own.

OWNS: the shape of a gate Job. It is built here rather than kept as a YAML file
because the pytest arguments must reach the pod verbatim, which string
templating gets wrong, and because a template beside the manifests would be
created by the next `kubectl apply` of that directory.

DOES NOT OWN: when a Job is made, how long it is waited for (`__main__.py`), or
how its end is read (`_outcome.py`).

THE IMAGE. The run container is the gate image the GATED commit's own
`infra/gate-image/pin` names by digest, never main's and never a tag, so a
commit is judged in the environment its own tree pins. A pin that names no
digest builds no Job at all (the caller reads that as 125, amber): there is no
second environment to fall back to.

A CLONE PER JOB, NOT A SHARED MIRROR. The fetch (init container, from the
deploy-cycle image, which has git) clones main in full into the Job's own
emptyDir and checks the commit out there; the run container reads that tree.
Full, never blobless or shallow: a test that reads an old blob would otherwise
fetch it from the network mid-suite, and a network blip would be a red that
takes an innocent commit back. Owning no claim is the point: a Job can land on
any gate node in any zone, so the number of Jobs at once is bounded by the gate
pools and nothing else. What a full clone per Job costs is not measured.

THE TOKEN. A read-only token for a private repository is the `token` key of
Secret `deploy-git-read`, mounted (optional) into the fetch container only.
The run container gets no token, no service account token and a clean `env -i`
for pytest: the suite must stay off the cluster's API and off GitHub.

THE SCRIPTS. `gate_fetch.sh` and `gate_run.sh` beside this file travel inside
the Job from the caller's checkout, every `$` doubled so Kubernetes passes
them to bash byte for byte, so no image carries a script of ours that could go
stale in it.

FAILURE POLICY: a bad argument raises ValueError; nothing here does I/O except
reading the two scripts.
"""
from __future__ import annotations

from pathlib import Path

_HERE = Path(__file__).resolve().parent
TREE = "/work/tree"
_TOKEN_DIR = "/var/run/deploy/git"


def pinned_gate_image(text: str) -> str:
    """The reference the pin file's last non-comment line names, or '' when it names no digest."""
    lines = [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    reference = lines[-1] if lines else ""
    return reference if "@sha256:" in reference else ""


def _inline(script: str, *argv: str) -> list:
    """`bash -c <script> <name> ARGV`, with every `$` doubled for Kubernetes."""
    body = (_HERE / script).read_text(encoding="utf-8").replace("$", "$$")
    return ["bash", "-c", body, script, *argv]


def _env(pairs: list) -> list:
    return [{"name": name, "value": str(value)} for name, value in pairs]


def gate_job_manifest(
    *,
    name: str,
    namespace: str,
    sha: str,
    repo_url: str,
    gate_image: str,
    cycle_image: str,
    pool_label: str,
    pytest_args: list,
    seconds: int,
    setup_seconds: int,
    changed_paths: str = "",
    replay_workers: int = 1,
    ref: str = "",
    cpu: str = "2",
    memory: str = "6Gi",
) -> dict:
    """One batch/v1 Job that runs pytest with `pytest_args` against commit `sha` and exits with its code.

    `changed_paths`: the commit's changed paths, one per line; when non-empty
    and the suite is green, the register's break replay runs in the same pod.
    `ref`: a ref to fetch when `sha` is not on main (a pull request's merge).
    """
    if "@sha256:" not in gate_image:
        raise ValueError(f"the gate image must be pinned by digest, got {gate_image!r}")
    if len(sha) != 40:
        raise ValueError(f"a gate Job runs one full commit sha, got {sha!r}")
    if not pytest_args:
        raise ValueError("a gate Job needs the paths or flags pytest runs")
    labels = {
        "app.kubernetes.io/name": "deploy-gate",
        "app.kubernetes.io/part-of": "deploy-loop",
        "harness/gate-sha": sha[:12],
    }
    fetch = {
        "name": "fetch",
        "image": cycle_image,
        "imagePullPolicy": "IfNotPresent" if "@sha256:" in cycle_image else "Always",
        "command": _inline("gate_fetch.sh"),
        "env": _env([("GATE_SHA", sha), ("GATE_REF", ref), ("GATE_TREE", TREE), ("GATE_REPO_URL", repo_url),
                     ("GATE_TOKEN_FILE", f"{_TOKEN_DIR}/token")]),
        "resources": {"requests": {"cpu": "500m", "memory": "512Mi"}, "limits": {"memory": "2Gi"}},
        "volumeMounts": [{"name": "work", "mountPath": "/work"},
                         {"name": "git-read", "mountPath": _TOKEN_DIR, "readOnly": True}],
    }
    run = {
        "name": "run",
        "image": gate_image,
        "imagePullPolicy": "IfNotPresent",
        "command": _inline("gate_run.sh", *pytest_args),
        "workingDir": TREE,
        "env": _env([("GATE_TREE", TREE), ("GATE_SECONDS", int(seconds)),
                     ("GATE_CHANGED_PATHS", changed_paths), ("GATE_REPLAY_WORKERS", int(replay_workers))]),
        "resources": {"requests": {"cpu": cpu, "memory": memory}, "limits": {"memory": memory}},
        "volumeMounts": [{"name": "work", "mountPath": "/work"}],
    }
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": name, "namespace": namespace, "labels": labels},
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": int(seconds) + int(setup_seconds),
            "ttlSecondsAfterFinished": 3600,
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "restartPolicy": "Never",
                    "automountServiceAccountToken": False,
                    "nodeSelector": {pool_label: "gate"},
                    "tolerations": [{"key": pool_label, "operator": "Equal", "value": "gate",
                                     "effect": "NoSchedule"}],
                    "priorityClassName": "deploy-loop",
                    "imagePullSecrets": [{"name": "registry-pull"}],
                    "securityContext": {"runAsUser": 1000, "runAsGroup": 1000, "fsGroup": 1000,
                                        "runAsNonRoot": True},
                    "initContainers": [fetch],
                    "containers": [run],
                    "volumes": [
                        {"name": "work", "emptyDir": {"sizeLimit": "20Gi"}},
                        {"name": "git-read", "secret": {"secretName": "deploy-git-read", "optional": True,
                                                        "defaultMode": 0o440}},
                    ],
                },
            },
        },
    }
