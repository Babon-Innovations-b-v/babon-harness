"""The stack's own images, and which Dockerfile builds each.

OWNS: the list step 50 builds and rolls from. An image is the stack's own when
a manifest under `infra/k8s/` names it `${IMAGE_REGISTRY}/<name>:set-by-deploy-loop`
(the placeholder the deploy loop replaces by digest), and it is built from the
compose service of the same `<name>` that has a `build:` block: its `context`
and `dockerfile`, as compose reads them (the context relative to the fragment's
directory, the Dockerfile relative to the context), returned relative to the
repository root. Which images a commit changes is
still `infra/auto-deploy/compose_fragments.py`'s answer; this only says how to
build one.

A placeholder with no compose service to build it is returned with an empty
`dockerfile`, so the step refuses it by name instead of skipping it.

FAILURE POLICY: an unreadable file contributes nothing; nothing raises.
"""
from __future__ import annotations

import posixpath
import re
from pathlib import Path

PLACEHOLDER_TAG = "set-by-deploy-loop"
_IMAGE = re.compile(r"\$\{IMAGE_REGISTRY\}/([a-z0-9][a-z0-9._-]*):" + PLACEHOLDER_TAG)
_FRAGMENT_PARENTS = ("apps", "infra", "lib")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _service_block(text: str, service: str) -> list:
    """The lines of `service` under the top-level `services:` of one compose fragment."""
    lines, inside, section = [], False, ""
    for raw in text.splitlines():
        if raw.strip() and not raw.startswith(" "):
            section = raw.split(":", 1)[0].strip()
            inside = False
            continue
        if section != "services":
            continue
        if raw.startswith("  ") and not raw.startswith("   ") and raw.strip().endswith(":"):
            inside = raw.strip().rstrip(":").strip("\"'") == service
            continue
        if inside:
            lines.append(raw)
    return lines


def _build_of(block: list) -> tuple:
    """(context, dockerfile) from a service block's `build:` mapping, or ('', '')."""
    context, dockerfile, in_build, depth = "", "", False, 0
    for raw in block:
        stripped = raw.strip()
        indent = len(raw) - len(raw.lstrip())
        if stripped.startswith("build:"):
            in_build, depth = True, indent
            inline = stripped[len("build:"):].strip()
            if inline:
                context = inline
            continue
        if in_build and stripped and indent <= depth:
            in_build = False
        if in_build and stripped.startswith("context:"):
            context = stripped.split(":", 1)[1].strip().strip("\"'")
        elif in_build and stripped.startswith("dockerfile:"):
            dockerfile = stripped.split(":", 1)[1].strip().strip("\"'")
    return context, dockerfile or ("Dockerfile" if context else "")


def stack_images(repo: Path) -> list:
    """[{name, context, dockerfile}] for every placeholder image, sorted by name.

    `context` and `dockerfile` are relative to the repository root; both are ''
    when no compose service of that name has a `build:` block.
    """
    names = set()
    for manifest in sorted((repo / "infra" / "k8s").glob("**/*.yaml")):
        names.update(_IMAGE.findall(_read(manifest)))
    fragments = [fragment for parent in _FRAGMENT_PARENTS for fragment in sorted((repo / parent).glob("*/compose.yml"))]
    images = []
    for name in sorted(names):
        context = dockerfile = ""
        for fragment in fragments:
            found_context, found_dockerfile = _build_of(_service_block(_read(fragment), name))
            if found_context:
                home = fragment.parent.relative_to(repo).as_posix()
                context = posixpath.normpath(posixpath.join(home, found_context))
                dockerfile = posixpath.normpath(posixpath.join(context, found_dockerfile))
                break
        images.append({"name": name, "context": context, "dockerfile": dockerfile})
    return images
