"""Which modules no row pins, worked out from the tree rather than typed.

OWNS: the gap between the modules in the tree and the modules the register
names, and the refusal `--check` makes of a module or module group no row tests
(`untested`).

DOES NOT OWN: what counts as a module (`_modules.py`), the rows (`_rows.py`),
or what the gate does with the number (the deploy gate reports it).

WHY IT IS DERIVED. A hand-kept list of modules without tests is a list that
rots: it is longest on the day it is written and wrong within the week, and
nobody notices, because a stale entry looks exactly like a real gap. The tree
already knows which modules exist and the register already knows which ones a
test pins, so the difference is a subtraction, not a document.

A module is covered when a row pins it, or pins any directory above it: the
standard makes a Tier M package one module whose layers are its implementation,
so a row that pins the package has covered the layers under it.

WHY NO TEST IS REFUSED, NOT ONLY COUNTED. A number nothing acts on lets a commit
add a module, or delete a module's only test, and land green. `untested` counts
a level only by the rows whose level it is (`_level.py`): a group test does not
cover the modules inside the group, and a module test does not cover its group.
`--check` (the pre-commit hook and the deploy gate) refuses every level it
names, with no debt list. A second test is `_second.py`'s refusal, a second
function in one file `_functions.py`'s.
"""
from __future__ import annotations

import posixpath
from collections import Counter
from collections.abc import Collection, Iterable, Sequence

from ._level import GROUP_SUFFIX, group_key, level_of
from ._row import Row


def uncovered(modules: Iterable[str], rows: Sequence[Row]) -> tuple[str, ...]:
    """The modules in the tree that no row pins, sorted."""
    pinned = {pin for row in rows for pin in row.pins}
    return tuple(sorted(module for module in modules if not _is_covered(module, pinned)))


def _is_covered(module: str, pinned: set[str]) -> bool:
    """True when this module, or a directory above it, is pinned by some row."""
    walked = module
    while walked:
        if walked in pinned:
            return True
        walked = posixpath.dirname(walked)
    return False


def untested(
    rows: Sequence[Row],
    modules: Collection[str],
    groups: Collection[str],
    debt: Collection[str] = (),
) -> tuple[str, ...]:
    """A refusal for every module and module group no row tests and `debt` does not excuse.

    Modules first, then groups, then every `debt` entry that excuses nothing.
    """
    counted = Counter(level_of(row, modules, groups) for row in rows)
    levels = (
        ("module", sorted(modules)),
        ("module group", sorted(group_key(group, modules) for group in groups)),
    )
    bare = {level for _label, keys in levels for level in keys if counted[level] == 0}
    refusals = [
        _refusal(level, label)
        for label, keys in levels
        for level in keys
        if level in bare and level not in debt
    ]
    refusals.extend(
        f"{level} is on the no-test debt list but is no untested level any more: "
        f"delete its entry in tools/test_register/_debt.py"
        for level in sorted(set(debt) - bare)
    )
    return tuple(refusals)


def _refusal(level: str, label: str) -> str:
    """The sentence one untested level is refused with, naming the command that fixes it."""
    directory = level.removesuffix(GROUP_SUFFIX)
    return (
        f"{level} is a {label} with no test, and every module and module group has "
        f"exactly one. Write it with `python3 -m tools.test_register "
        f"--new {directory} --says \"<invariant>\"`"
        + (", then pin two or more of the modules under it in its row" if label == "module group" else "")
        + "."
    )
