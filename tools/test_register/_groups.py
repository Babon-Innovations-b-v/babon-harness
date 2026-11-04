"""What counts as a module group, worked out from the modules rather than typed.

OWNS: the definition of a module group, and which group a selected test path
runs with when a selection is split over several gate runs (`shards`).

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

THE KEY. A path that is a row's test file keys by the level that row tests: a
module group's test is that group, a module's test is the innermost module
group holding the module. Any other path (a directory the selector collapsed
to, a file with no row, a level that is a crossing of several pins) keys by the
innermost module group holding the path itself, and a path in no group keys by
its first two path parts, so `docs` is a shard of its own.

PACKING. One shard per key while there are at most `limit` keys. With more,
keys are placed heaviest first into the shard lightest so far, the earlier
shard on a tie, so the same selection always gives the same shards. A path
weighs the number of test files it holds (a file one, a directory every row
under it, at least one); a key weighs its paths. A shard is named by its keys
joined with ` + `. More gate nodes take more shards, which is how throughput
grows with the cluster.

FAILURE POLICY. Pure: no I/O, no exception for any input.
"""
from __future__ import annotations

import posixpath
from collections import Counter
from collections.abc import Collection, Iterable

from ._level import GROUP_SUFFIX, level_of
from ._modules import LAYER_NAMES
from ._row import Row


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


def _nearest_group(path: str, groups: Collection[str]) -> str:
    """The innermost module group holding `path` (or equal to it), '' when none does."""
    walked = path.rstrip("/")
    while walked:
        if walked in groups:
            return walked
        walked = posixpath.dirname(walked)
    return ""


def shard_key(path: str, row: Row | None, modules: Collection[str], groups: Collection[str]) -> str:
    """The module group one selected path runs with."""
    if row is not None:
        level = level_of(row, modules, groups)
        if level.endswith(GROUP_SUFFIX):
            return level[: -len(GROUP_SUFFIX)]
        if level in groups:
            return level
        if " + " not in level:
            found = _nearest_group(posixpath.dirname(level), groups)
            if found:
                return found
    found = _nearest_group(path, groups)
    if found:
        return found
    return "/".join(path.strip("/").split("/")[:2])


def shards(
    paths: Iterable[str],
    rows: Iterable[Row],
    modules: Collection[str],
    groups: Collection[str],
    limit: int,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """The selected paths as (name, paths) shards, at most `limit` of them, sorted by name."""
    by_test = {row.test: row for row in rows}
    keyed: dict[str, list[str]] = {}
    weight: dict[str, int] = {}
    for path in dict.fromkeys(path.strip() for path in paths if path.strip()):
        key = shard_key(path, by_test.get(path), modules, groups)
        keyed.setdefault(key, []).append(path)
        prefix = path.rstrip("/") + "/"
        held = sum(1 for test in by_test if test == path or test.startswith(prefix))
        weight[key] = weight.get(key, 0) + max(1, held)
    order = sorted(keyed, key=lambda key: (-weight[key], key))
    bins: list[tuple[list[str], list[str], list[int]]] = []
    for key in order:
        if len(bins) < max(1, limit):
            bins.append(([key], list(keyed[key]), [weight[key]]))
            continue
        target = min(range(len(bins)), key=lambda index: (bins[index][2][0], index))
        bins[target][0].append(key)
        bins[target][1].extend(keyed[key])
        bins[target][2][0] += weight[key]
    return tuple(
        sorted((" + ".join(sorted(keys)), tuple(sorted(members))) for keys, members, _ in bins)
    )
