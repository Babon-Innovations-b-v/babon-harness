"""Paths and process helpers shared by the diagram tools.

Everything runs against the repository checkout: the specs live in
``docs/diagrams/specs/``, the build tooling in ``docs/diagrams/tools/``, the
build sidecars in ``docs/diagrams/data/``, and the delivered pages in
``docs/diagrams/`` and ``docs/diagrams/stack/``. The served tree holds nothing
but ``.html``, so it can be published as it stands, and a page
and its sidecars are always one directory apart: ``stack/<name>.html`` beside
``data/stack/<name>.architecture.json``.

FAILURE POLICY: nothing here decides anything. ``run`` captures both streams and
hands the completed process back whole, so the tool that called it owns what a
non-zero exit means; only a build that hangs past the timeout raises. The paths
are derived from this file's own location, so a checkout anywhere works, and a
tool that finds one of them missing says which one moved rather than guessing.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess

REPO = pathlib.Path(__file__).resolve().parents[3]
DIAGRAMS = REPO / "docs" / "diagrams"
SPECS = DIAGRAMS / "specs"
TOOLS = DIAGRAMS / "tools"
DATA = DIAGRAMS / "data"
STACK = DIAGRAMS / "stack"
STACK_DATA = DATA / "stack"
LINKMAP = TOOLS / "linkmap.py"
STRIP_CHROME = TOOLS / "strip-chrome.py"
BUILD_FREE = TOOLS / "build_free.py"


#: Where the published docs/ tree lives, from config/harness.env. Empty means
#: relative links, the same rule ``linkmap.py`` follows.
SITE = os.environ.get("BIBLE_BASE_URL", "").rstrip("/")
#: The prefix a bible marker is written with, as ``linkmap.py`` writes it.
MARKER_PREFIX = f"{SITE}/diagrams/" if SITE else "diagrams/"


def run(cmd: list[str], timeout: int = 900) -> subprocess.CompletedProcess:
    """Run a build step from the repository root, capturing both streams."""
    return subprocess.run(
        cmd, cwd=REPO, capture_output=True, text=True, timeout=timeout
    )


def write_spec(name: str, spec: dict, layout: dict) -> pathlib.Path:
    """Store a page's two spec files so it can be rebuilt without re-authoring.

    The facts live in ``<name>.json`` and the shape in ``<name>.layout.json``,
    which is the split ``build_free.py`` reads (docs/diagrams/tools/REDRAW-BRIEF.md).
    """
    folder = SPECS / "stack"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.json"
    path.write_text(json.dumps(spec, indent=1) + "\n")
    (folder / f"{name}.layout.json").write_text(json.dumps(layout, indent=1) + "\n")
    return path


def page_paths(name: str) -> dict[str, pathlib.Path]:
    """Where a stack page's source, sidecars and delivered HTML live."""
    return {
        "source": STACK_DATA / f"{name}.architecture.json",
        "notes": STACK_DATA / f"{name}.notes.json",
        "modules": STACK_DATA / f"{name}.modules.json",
        "html": STACK / f"{name}.html",
    }


def unclaimed_boxes(page: str) -> list[str]:
    """Box ids on this page that no bible sentence claims yet.

    A box is claimed by a ◈ marker in a bible section body, and
    ``linkmap.py`` writes the page's ``links.json`` from those markers, so a
    box missing from that file has no paragraph explaining it.
    """
    folder = DATA if page == "stack" else STACK_DATA
    source = folder / f"{page}.architecture.json"
    if not source.exists():
        source = folder / f"{page}.workflow.json"
    if not source.exists():
        return []
    doc = json.loads(source.read_text())
    boxes = [box["id"] for box in doc.get("components") or doc["nodes"]]
    links_path = folder / f"{page}.links.json"
    claimed = json.loads(links_path.read_text()) if links_path.exists() else {}
    return [box for box in boxes if box not in claimed]
