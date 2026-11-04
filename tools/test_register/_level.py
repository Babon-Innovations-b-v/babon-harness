"""Which level one row tests: a module, a module group, or what it names itself.

OWNS: turning a row's `pins` into the one key the one-test-per-level rule
counts by.

DOES NOT OWN: what a module or a group is (`_modules.py`, `_groups.py`).

A ROW DECLARES ITS LEVEL BY WHAT IT PINS. No extra field: a pin that names a
module or a module group is that level; a pin inside a module (a file in it, a
subdirectory that is not a module) is that module. A pin outside every module,
such as `.claude/hooks`, is its own key
as written, so the rule still holds there even though the tree map does not
draw it.

A row with several pins tests how those pieces fit, which is the job of the
group they sit in: its key is the nearest module group holding all of them.
A directory that is a module AND a group (`_groups.py`) is the module for a pin
on it or its layers, its own code, and the group only for a row whose pins it
holds together; the group's key then reads `<directory> (group)`.
Where no group holds them all, or a pin is outside the tree map (`.claude/hooks`
with `tools/gate_scope`), the key is the pins' keys joined with ` + `, so two
tests of the same crossing still count as two.
"""
from __future__ import annotations

import posixpath
from collections.abc import Collection

from ._modules import LAYER_NAMES
from ._row import Row


#: What a group's key carries after the directory when the directory is a module too.
GROUP_SUFFIX = " (group)"


def group_key(group: str, modules: Collection[str]) -> str:
    """The key a module group is counted by: its directory, marked when it is a module too."""
    return f"{group}{GROUP_SUFFIX}" if group in modules else group


def level_of(row: Row, modules: Collection[str], groups: Collection[str]) -> str:
    """The module, module group or declared unit this row is the test of."""
    keys = sorted({_key_of_pin(pin, modules, groups) for pin in row.pins})
    if len(keys) == 1:
        return keys[0]
    if all(key in modules or key in groups for key in keys):
        walked = posixpath.commonpath(keys)
        while walked:
            if walked in groups:
                return group_key(walked, modules)
            walked = posixpath.dirname(walked)
    return " + ".join(keys)


def _key_of_pin(pin: str, modules: Collection[str], groups: Collection[str]) -> str:
    """The pin itself if it is a module or group, else the module it sits in.

    A pin in a layer of a module group (`<group>/gates`) is that group:
    the layers of a group are its own glue code (`_modules.py`).
    """
    pin = pin.rstrip("/")
    if pin in groups and pin not in modules:
        return pin
    walked = pin
    while walked:
        if walked in modules:
            return walked
        parent = posixpath.dirname(walked)
        if (
            parent in groups
            and parent not in modules
            and posixpath.basename(walked) in LAYER_NAMES
        ):
            return parent
        walked = parent
    return pin
