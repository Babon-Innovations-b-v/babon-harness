"""`decide(changed, repo)`, the one public callable of the gate scope.

Three tiers, and the fallback on anything unproven is always the wider one:

  `full`      the whole suite;
  `selected`  the union of the reverse import closure, conftest expansion,
              own-package tests, the narrowed floor and the register triggers;
  `none`      that union is empty. It is NOT a green gate: step 40 posts no
              `vm/gate` status for it, and the nightly unselected audit in
              `audit_full_run.sh` is what actually verifies the commit.

FAILURE POLICY: `decide` never raises and never returns anything but a
Decision. Every internal error (a missing repo, an unreadable file, a
`SyntaxError` in first-party code, a `--ignore` list it cannot read out of the
gate step) comes back as `Decision("full", ...)` with the reason in place.
A selector that cannot decide has not found a safe commit; it has found a
commit it knows nothing about.
"""
from __future__ import annotations

import posixpath
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Literal

from tools.test_register import ROWS, triggers_for
from . import _floor, _graph
from ._classify import FULL_FORCING, PYTHON, classify, is_test_file

#: The gate step this decision is consumed by. Its `--ignore` flags are read
#: back out so the selection can never name a path pytest refuses to collect:
#: a selection of nothing but ignored paths exits rc=5, and step 40 reads rc=5
#: under a selection as RED.
GATE_STEP = "infra/auto-deploy/steps/40-gate.sh"
_IGNORE_FLAG = re.compile(r"--ignore=(\S+)")


@dataclass(frozen=True)
class Decision:
    """What the gate should run, and why."""

    scope: Literal["none", "selected", "full"]
    paths: tuple[str, ...] = ()
    reason: str = ""
    counts: Mapping[str, int] = field(default_factory=dict)


def decide(changed: Sequence[str], repo: Path) -> Decision:
    """Decide the gate scope for one commit's changed paths."""
    try:
        return _decide(changed, repo)
    except Exception as failure:  # noqa: BLE001, the fallback IS the policy
        return Decision("full", (), f"selector failed: {failure!r}", {})


def _decide(changed: Sequence[str], repo: Path) -> Decision:
    paths = tuple(path.strip() for path in changed if path and path.strip())
    if not paths:
        return Decision("full", (), "no changed paths given", {"changed": 0})

    for path in paths:
        if classify(path) == FULL_FORCING:
            return Decision(
                "full", (), f"{path} is not proven safe to narrow", {"changed": len(paths)}
            )

    ignored = _gate_ignores(repo)
    if not ignored:
        return Decision(
            "full",
            (),
            f"could not read the --ignore list out of {GATE_STEP}",
            {"changed": len(paths)},
        )

    graph = _graph.build(repo)
    if graph.unparseable:
        sample = sorted(graph.unparseable)[0]
        return Decision(
            "full",
            (),
            f"the import graph is incomplete: {sample} does not parse",
            {"changed": len(paths)},
        )

    # A deleted TEST file is the one exception, and it is exact rather than
    # convenient: pytest COLLECTS a test file rather than importing it from
    # anywhere else, so nothing in the tree can be broken by its removal.
    #
    # It is deliberately NOT extended to a deleted source file: a reverse
    # closure from a file that is gone is empty, and empty reads as "nothing
    # depends on it" when what it means is "we cannot tell".
    gone = [
        path
        for path in paths
        if classify(path) == PYTHON
        and path not in graph.rdeps
        and not is_test_file(path)
    ]
    # A source file the graph has never heard of was DELETED, or MOVED, which
    # git reports as a delete plus an add. `rdeps` can only record an edge
    # whose target exists, so it is the wrong index to ask; `graph.references`
    # keeps the raw names every file mentions, resolved or not, so the question
    # can be asked the other way round: who still NAMES the thing that is gone.
    #
    # Two answers, and both are better than the whole suite:
    #   - nobody names it. The removal broke nothing, every importer was
    #     updated in this same commit and is already a seed.
    #   - somebody names it. Those files are broken right now, and seeding the
    #     closure with them runs the tests that reach them.
    #
    # It stays `full` only when the question cannot be asked at all: a path
    # that yields no dotted name from any sys.path root (a hyphenated
    # directory, a leading digit).
    stranded: set[str] = set()
    unnameable = []
    for path in gone:
        lost = _graph.module_names(path, graph.roots)
        if not lost:
            unnameable.append(path)
            continue
        stranded.update(
            holder
            for holder, referenced in graph.references.items()
            if referenced & lost
        )
    unknown_python = unnameable
    if unknown_python:
        # A gone `.py` that answers to no dotted name from any sys.path root:
        # a hyphenated directory, a leading digit. Nothing could have imported
        # it by name, so `graph.references` cannot be asked about it either,
        # and an unanswerable question takes the loud direction.
        return Decision(
            "full",
            (),
            f"{unknown_python[0]} is not in the tree and answers to no module "
            "name, so nothing can be said about its importers",
            {"changed": len(paths)},
        )

    floor = _floor.derive(graph, repo)
    collectable = frozenset(
        path
        for path in _floor.collected_test_files(graph)
        if not _is_ignored(path, ignored)
    )

    # `stranded` is every file that still names a module this commit removed.
    # They are seeds like any changed file, because they are broken in exactly
    # the way the removal broke them, and the tests that reach them are what
    # has to run. Empty on a clean move, which is the common case.
    closure = _graph.reverse_closure(
        graph,
        {path for path in paths if classify(path) == PYTHON} | stranded,
    )
    selected: set[str] = {path for path in closure if path in collectable}
    selected |= _conftest_expansion(closure, collectable)
    selected |= _own_package_tests(paths, collectable)
    selected |= _narrowed_floor(floor, collectable, paths)
    selected |= _triggered_tests(collectable, paths)

    counts = {
        "changed": len(paths),
        "closure": len(closure),
        "floor": len(floor),
        "paths": 0,
    }
    if not selected:
        return Decision("none", (), "no test can reach any changed path", counts)

    compressed = _compress(selected, collectable)
    if not selection_is_only_test_paths(compressed, repo):
        # The invariant, enforced where the decision is made rather than only in
        # a test. Handing pytest a non-test source file makes it import that
        # file as a test module, which can abort the run (exit 2, red) on a
        # settings module that refuses to import outside production. Falling
        # back to `full` costs a slow cycle and verifies everything.
        return Decision(
            "full",
            (),
            "the selection contained something that is not a test path",
            {**counts, "paths": 0},
        )
    counts["paths"] = len(compressed)
    # How many test FILES this runs, beside how many arguments pytest is handed.
    # The two differ whenever `_compress` folds a directory, so a caller asking
    # "how much of the suite is this" must read `selected`, never `paths`.
    counts["selected"] = len(selected)
    return Decision(
        "selected",
        compressed,
        f"{len(selected)} test files reachable from {len(paths)} changed paths",
        counts,
    )


def _gate_ignores(repo: Path) -> tuple[str, ...]:
    """The `--ignore=` paths the gate passes pytest, read from the step file."""
    try:
        text = (repo / GATE_STEP).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ()
    return tuple(_IGNORE_FLAG.findall(text))


def _is_ignored(path: str, ignored: tuple[str, ...]) -> bool:
    """True when the gate's own `--ignore` flags drop this file."""
    return any(path == entry or path.startswith(entry + "/") for entry in ignored)


def _conftest_expansion(closure: frozenset[str], collectable: frozenset[str]) -> set[str]:
    """A reached `conftest.py` pulls in every test in its directory.

    Fixtures are an import edge no graph can see from the test's side: the
    tests in a directory import nothing, the conftest does, and every test
    there runs through its fixture.
    """
    expanded: set[str] = set()
    for path in closure:
        if posixpath.basename(path) != "conftest.py":
            continue
        directory = posixpath.dirname(path)
        prefix = f"{directory}/" if directory else ""
        expanded |= {test for test in collectable if test.startswith(prefix)}
    return expanded


def _own_package_tests(paths: Sequence[str], collectable: frozenset[str]) -> set[str]:
    """A changed package always runs its own tests, importers or not.

    Without this a leaf module nothing depends on would select nothing at all.
    """
    owned: set[str] = set()
    for path in paths:
        #: An overlay is not the package's code, so it does not own the
        #: package's tests. Same rule as `_fires` below.
        if posixpath.basename(path) == "CLAUDE.md":
            continue
        directory = posixpath.dirname(path)
        if not directory:
            continue
        prefix = f"{directory}/tests/"
        owned |= {test for test in collectable if test.startswith(prefix)}
    return owned


def _narrowed_floor(
    floor: frozenset[str], collectable: frozenset[str], paths: Sequence[str]
) -> set[str]:
    """The floor, minus the tests whose narrowing triggers no change matched."""
    kept: set[str] = set()
    for test in floor:
        if test not in collectable:
            continue
        triggers = triggers_for(test)
        if triggers is None:
            kept.add(test)
            continue
        if any(_fires(path, glob) for path in paths for glob in triggers):
            kept.add(test)
    return kept


def _fires(path: str, glob: str) -> bool:
    """Does one changed path match one trigger glob?

    THE OVERLAY RULE. A `CLAUDE.md` fires only a trigger that names `.md`
    itself. Every other trigger it matches is a directory glob, and a directory
    glob is a statement about the CODE in that directory: an overlay is prose
    Claude Code loads at runtime, imported by nothing. Without this rule a
    paragraph of prose in a directory's overlay selects that directory's whole
    suite.

    It is deliberately about `CLAUDE.md` and not about `.md`: `docs/bible.md`
    and the decision records can be read by real tests, whose rows name `.md`,
    so they are untouched either way.
    """
    if not fnmatchcase(path, glob):
        return False
    if posixpath.basename(path) == "CLAUDE.md":
        return ".md" in glob
    return True


def _triggered_tests(collectable: frozenset[str], paths: Sequence[str]) -> set[str]:
    """Every test whose register row a change matched.

    The subtractive pass above can only keep a test the floor already found,
    and `_floor.derive` cannot see a test that reaches the tree through an
    imported function. Adding the row's test outright is what closes that.
    """
    return {
        row.test
        for row in ROWS
        if row.test in collectable
        and any(_fires(path, glob) for path in paths for glob in row.runs_when)
    }


def _compress(selected: set[str], collectable: frozenset[str]) -> tuple[str, ...]:
    """Fold a directory whose every collectable test is selected into one path.

    pytest collects only `test_*.py` / `*_test.py` under a directory argument,
    so naming the directory runs exactly the selected files and nothing more.
    """
    by_directory: dict[str, set[str]] = {}
    for test in collectable:
        directory = posixpath.dirname(test)
        while True:
            by_directory.setdefault(directory, set()).add(test)
            if not directory:
                break
            directory = posixpath.dirname(directory)

    covered = {
        directory
        for directory, tests in by_directory.items()
        if directory and tests <= selected
    }
    maximal = {
        directory
        for directory in covered
        if not any(
            directory != other and directory.startswith(other + "/") for other in covered
        )
    }
    kept: set[str] = set(maximal)
    for test in selected:
        if not any(test.startswith(directory + "/") for directory in maximal):
            kept.add(test)
    return tuple(sorted(kept))


def selection_is_only_test_paths(paths: Sequence[str], repo: Path) -> bool:
    """True when every selected path is a directory or a collectable test file.

    Handing pytest a non-test source file makes it import that file as a test
    module, which can abort the whole run. A selection is only ever test files
    and directories.
    """
    for path in paths:
        if (repo / path).is_dir():
            continue
        if not is_test_file(path):
            return False
    return True
