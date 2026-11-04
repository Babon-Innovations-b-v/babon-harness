"""What counts as a module group, worked out from the modules rather than typed.

OWNS: the definition of a module group.

DOES NOT OWN: what a module is (`_modules.py`), or how many tests a group has
(`_second.py`).

THE RULE. A module group is a directory under which two or more modules sit, at
any depth, that is not a layer (the five names in `LAYER_NAMES`), not a `tests`
directory and not the repository root. `apps` and `tools` are groups whenever
two modules sit under them, because every level has its own test and the full
suite is the only level above them.

A MODULE CAN ALSO BE A GROUP. A module with two or more modules under it is a
group as well: its own code is still the module, and a test of how the modules
under it fit is the group's test. The two levels share a directory, so
`_level.group_key` writes the group's key with ` (group)` after it.

Derived from the module list and nothing else, so the same tree always gives the
same groups, and a group appears or disappears the moment its second module does.
"""
from __future__ import annotations

import posixpath
from collections import Counter
from collections.abc import Iterable

from ._modules import LAYER_NAMES


def module_groups(modules: Iterable[str]) -> tuple[str, ...]:
    """Every module group the given modules imply, sorted."""
    module_set = set(modules)
    below: Counter[str] = Counter()
    for module in module_set:
        parent = posixpath.dirname(module)
        while parent:
            below[parent] += 1
            parent = posixpath.dirname(parent)
    return tuple(
        sorted(
            directory
            for directory, count in below.items()
            if count >= 2
            and posixpath.basename(directory) not in LAYER_NAMES
            and "tests" not in directory.split("/")
        )
    )
