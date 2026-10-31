"""Settings the notulen dashboard reads from its environment.

Owns: the template path, the S3 location, where the minutes are committed
(repository and folder) and whether the GPU tier is switched on. Does NOT own
the S3 client (``shared/s3.py``) or any DB access (``shared/update_job.py``).

Everything here comes from ``config/harness.env`` and the vault, which compose
hands the container as its environment. The repository defaults to the
``repo`` field of ``.claude/project.json`` when ``NOTULEN_TARGET_REPO`` is
unset, so a checkout run outside compose (tests, a developer box) still knows
where its minutes go.

Accessors are read at call time, so a test can change the environment
between calls and the next call sees it.

FAILURE POLICY: pure env and file reads. ``target_repo`` raises
``KeyError`` when neither source names a repository, because a commit to a
guessed repository is worse than no commit.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = _PACKAGE_ROOT.parents[1]

#: The minutes template, shipped inside the package so both the dashboard
#: image and the GPU worker image carry the same file.
TEMPLATE_PATH = Path(
    os.environ.get("NOTULEN_TEMPLATE_PATH", _PACKAGE_ROOT / "inputs" / "notulen_template.md")
)

#: Where the recordings are stored. fr-par is only the default value; the
#: bucket must exist in the region the endpoint names.
S3_REGION = os.environ.get("S3_REGION") or os.environ.get("SCW_REGION") or "fr-par"
S3_ENDPOINT = os.environ.get("S3_ENDPOINT") or f"https://s3.{S3_REGION}.scw.cloud"
S3_BUCKET = os.environ.get("S3_BUCKET", "")


def target_repo() -> str:
    """``owner/name`` of the repository the minutes are committed to."""
    explicit = os.environ.get("NOTULEN_TARGET_REPO", "").strip()
    if explicit:
        return explicit
    project_json = Path(os.environ.get("PROJECT_JSON", _REPO_ROOT / ".claude" / "project.json"))
    if project_json.exists():
        repo = str(json.loads(project_json.read_text(encoding="utf-8")).get("repo") or "").strip()
        if repo:
            return repo
    raise KeyError("NOTULEN_TARGET_REPO")


def target_branch() -> str:
    """The branch the minutes are committed to."""
    return os.environ.get("NOTULEN_TARGET_BRANCH", "main")


def target_folder() -> str:
    """Repo-relative folder the minutes land in, without a trailing slash."""
    return os.environ.get("NOTULEN_TARGET_PATH", "business/minutes").strip("/") or "business/minutes"


def gpu_enabled() -> bool:
    """True when the GPU tier is switched on and the cluster key is present.

    ``GPU_ENABLED=0`` (the default) keeps every recording on the CPU path even
    when a kubeconfig happens to be in the environment.
    """
    return os.environ.get("GPU_ENABLED", "0") == "1" and bool(kubeconfig_b64())


def kubeconfig_b64() -> str:
    """The base64 kubeconfig the dashboard uses to reach the GPU cluster."""
    return os.environ.get("KUBECONFIG_B64") or os.environ.get("KUBECONFIG_DATA", "")


def default_attendees() -> list[str]:
    """``NOTULEN_ATTENDEES``, the people offered as attendees by default."""
    raw = os.environ.get("NOTULEN_ATTENDEES", "")
    return [name.strip() for name in raw.split(",") if name.strip()]
