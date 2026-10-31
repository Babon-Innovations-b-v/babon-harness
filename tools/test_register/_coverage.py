"""Which modules no row pins, worked out from the tree rather than typed.

OWNS: the gap between the modules in the tree and the modules the register
names.

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
"""
from __future__ import annotations

import posixpath
from collections.abc import Iterable, Sequence

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
