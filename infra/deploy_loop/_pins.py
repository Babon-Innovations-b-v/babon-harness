"""Which running objects still name another tag of an image the cycle just built.

OWNS: the one question step 50 asks before `kubectl set image`: given the image
reference a deploy just pushed (`<registry>/<name>:git-<sha12>@sha256:...`),
which Deployments, StatefulSets, DaemonSets and CronJobs carry a container of
the same repository on any other tag or digest. A container already on that
exact reference is left out, so a re-run changes nothing.

THE REPOSITORY is the reference with its tag and digest taken off. A colon
after the last slash is a tag; a colon before it is a registry port, which the
repository keeps.

FAILURE POLICY: pure; an object of a kind it does not know contributes nothing.
"""
from __future__ import annotations

#: kind -> the path from the object to its pod spec.
_POD_SPEC_PATHS = {
    "Deployment": ("spec", "template", "spec"),
    "StatefulSet": ("spec", "template", "spec"),
    "DaemonSet": ("spec", "template", "spec"),
    "CronJob": ("spec", "jobTemplate", "spec", "template", "spec"),
}


def repository(reference: str) -> str:
    """`registry[:port]/path/name[:tag][@digest]` -> `registry[:port]/path/name`."""
    without_digest = reference.split("@", 1)[0]
    slash = without_digest.rfind("/")
    colon = without_digest.rfind(":")
    return without_digest[:colon] if colon > slash else without_digest


def _pod_spec(item: dict) -> dict:
    spec = item
    for key in _POD_SPEC_PATHS.get(item.get("kind", ""), ()):
        spec = spec.get(key) if isinstance(spec, dict) else None
        if spec is None:
            return {}
    return spec if isinstance(spec, dict) and spec is not item else {}


def image_targets(documents: list, image: str) -> list:
    """Every (namespace, kind, name, container) running `image`'s repository on another reference."""
    wanted = repository(image)
    found = set()
    for document in documents:
        if not isinstance(document, dict):
            continue
        items = document.get("items") if str(document.get("kind", "")).endswith("List") else [document]
        for item in items or []:
            if not isinstance(item, dict):
                continue
            metadata = item.get("metadata") or {}
            pod_spec = _pod_spec(item)
            for field in ("initContainers", "containers"):
                for container in pod_spec.get(field) or []:
                    current = str(container.get("image", ""))
                    if current == image or repository(current) != wanted:
                        continue
                    found.add((
                        str(metadata.get("namespace", "")),
                        str(item["kind"]).lower(),
                        str(metadata.get("name", "")),
                        str(container.get("name", "")),
                    ))
    return sorted(found)
