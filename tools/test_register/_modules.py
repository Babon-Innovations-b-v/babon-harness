"""What counts as a module in this tree.

OWNS: the definition. Nothing else here decides it, and every number the
register reports (`--coverage`, the one-test-per-level rule in `--check`) is
only as honest as this file.

DOES NOT OWN: module groups (`_groups.py`), which modules are covered
(`_coverage.py`).

THE RULE. A module is a package directory (it holds an `__init__.py`) with an
implementation file of its own, anywhere in our tree, with four exceptions
that are never modules, each folded into the directory that owns it:

  a layer          `core`, `gates`, `shared`, `entrypoints`, `inputs`. Its code
                   belongs to its parent: `apps/dashboards/notulen/app` is one
                   level with layers, not one per layer. The parent is a module,
                   unless two or more modules sit below it, which makes it a
                   module group whose own glue code the layers are.
  test data        `fixtures`, `migrations`: inputs a test or the database
                   reads, nothing a test pins on its own.
  a Django command `management/commands` is the entrypoint of the app above it.
  a test directory `tests` and anything under it.

A folder of code INSIDE a layer is a module of its own, such as
`apps/assistant/core/tools/meta`.

WHY THE OBVIOUS NUMBER IS WRONG. Counting every directory that holds an
`__init__.py` counts the containers that exist only so the packages below them
have a dotted name (`apps/`, `tools/`), the layers of one module five times
over, and a `tests` package. None of them is a unit a test pins.
"""
from __future__ import annotations

import posixpath
from pathlib import Path

#: The five layer names a Tier M/L package is built from. A layer is never a
#: module and never a module group; its code belongs to its parent.
LAYER_NAMES = frozenset({"core", "gates", "shared", "entrypoints", "inputs"})

#: Trees that are not ours to count: vendored code. Add a path here when the
#: repository vendors one; installed dependencies, build output and caches are
#: excluded by name below wherever they appear, because their presence depends
#: on which box you ask, which is exactly what a counted number must not.
NOT_OURS: tuple[str, ...] = ()

#: Files that make a directory a package or a framework root without being
#: implementation of their own (ADR-0002's carve-out list).
_NOT_IMPLEMENTATION = frozenset({"__init__.py", "conftest.py", "manage.py"})

#: Directory NAMES that hold data a test or the database reads, never a module,
#: wherever they appear in a path. `management` is Django's command entrypoint.
NOT_A_MODULE_ANYWHERE = frozenset(
    {"tests", "fixtures", "migrations", "management"}
)

#: Directory NAMES that mean "not ours" wherever they appear in a path.
NOT_OURS_ANYWHERE = frozenset(
    {".venv", "node_modules", "__pycache__", "dist", "build", "worktrees"}
)


def modules_in(repo: Path) -> tuple[str, ...]:
    """Every directory in the tree that reads as a module in its own right."""
    holding = _code_directories(repo)
    owners = {_owner(directory) for directory in holding}
    groups_by_layers = {
        owner
        for owner in owners
        if owner not in holding and _modules_below(owner, owners) >= 2
    }
    return tuple(sorted(owners - groups_by_layers))


def _code_directories(repo: Path) -> set[str]:
    """Every package of ours, outside tests and test data, with code of its own."""
    found = set()
    for init in repo.glob("**/__init__.py"):
        directory = init.parent.relative_to(repo).as_posix()
        if directory in (".", ""):
            continue
        if _is_not_ours(directory) or _is_not_a_module(directory):
            continue
        if _holds_code(init.parent):
            found.add(directory)
    return found


def _owner(directory: str) -> str:
    """The directory itself, or its parent when it is a layer of that parent."""
    if posixpath.basename(directory) in LAYER_NAMES and "/" in directory:
        return posixpath.dirname(directory)
    return directory


def _modules_below(directory: str, candidates: set[str]) -> int:
    """How many of `candidates` sit strictly under `directory`."""
    return sum(1 for candidate in candidates if candidate.startswith(f"{directory}/"))


def _holds_code(directory: Path) -> bool:
    """True when the package has an implementation file of its own.

    A package whose only `.py` is its `__init__.py` is a container that exists
    so the ones below it have a dotted name, such as `apps/`. Counting them as
    modules without a test is noise: there is nothing in them to test. The
    framework carve-out files do not count either: a directory holding only
    `manage.py` and `conftest.py` is a group of the modules below it.
    """
    return any(
        child.suffix == ".py" and child.name not in _NOT_IMPLEMENTATION
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


def _is_not_a_module(directory: str) -> bool:
    """True for a test directory, test data or a Django command, or anything under one."""
    return any(segment in NOT_A_MODULE_ANYWHERE for segment in directory.split("/"))
