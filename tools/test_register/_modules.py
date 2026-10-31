"""What counts as a module in this tree, for counting the gap.

OWNS: the definition. Nothing else here decides it, and the number the gate
posts is only as honest as this file.

DOES NOT OWN: which modules are covered (`_coverage.py`).

WHY THE OBVIOUS NUMBER IS WRONG. Counting every directory that holds an
`__init__.py` counts layers and test directories as modules. Those are the
inside of a module, not modules, so they are stripped before counting.
"""
from __future__ import annotations

import posixpath
from pathlib import Path

#: The five layer names a Tier M/L package is built from. A directory with one
#: of these names is a layer inside a module, never a module.
LAYER_NAMES = frozenset({"core", "gates", "shared", "entrypoints", "inputs"})

#: Trees that are not ours to count: vendored code. Add a path here when the
#: repository vendors one; installed dependencies and caches are excluded by
#: name below wherever they appear.
NOT_OURS: tuple[str, ...] = ()

#: Directory NAMES that mean "not ours" wherever they appear in a path.
NOT_OURS_ANYWHERE = frozenset(
    {".venv", "node_modules", "__pycache__", "dist", "build", "worktrees"}
)


def modules_in(repo: Path) -> tuple[str, ...]:
    """Every directory in the tree that reads as a module in its own right."""
    found = []
    for init in sorted(repo.glob("**/__init__.py")):
        directory = init.parent.relative_to(repo).as_posix()
        if directory in (".", ""):
            continue
        if _is_not_ours(directory) or _is_inside_a_module(directory):
            continue
        if not _holds_code(init.parent):
            continue
        found.append(directory)
    return tuple(found)


def _holds_code(directory: Path) -> bool:
    """True when the package has an implementation file of its own.

    A package whose only `.py` is its `__init__.py` is a container that exists
    so the ones below it have a dotted name. Counting them as modules without a test is noise: there is
    nothing in them to test.
    """
    return any(
        child.suffix == ".py" and child.name != "__init__.py"
        for child in directory.iterdir()
        if child.is_file()
    )


def _is_not_ours(directory: str) -> bool:
    """True when this path is under, or named after, a tree nobody here counts."""
    if any(segment in NOT_OURS_ANYWHERE for segment in directory.split("/")):
        return True
    return any(
        directory == tree or directory.startswith(f"{tree}/") for tree in NOT_OURS
    )


def _is_inside_a_module(directory: str) -> bool:
    """True for a layer, a test directory, or anything inside a `core/` layer."""
    name = posixpath.basename(directory)
    if name in LAYER_NAMES or name == "tests":
        return True
    return "/core/" in f"/{directory}/"
