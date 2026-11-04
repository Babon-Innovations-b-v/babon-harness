"""Which tests one gate run leaves out because they are quarantined.

OWNS: turning a selection (the test files and directories the gate would run)
and the quarantines the gate honours into what pytest is actually given.

DOES NOT OWN: which quarantines are honoured (`_row.gate_quarantines`), what
selects a path (`tools/gate_scope`), or what the gate does with an empty run
(the gate step reads `emptied`).

THE RULE. A quarantined test leaves the run and nothing else does. A selected
path that IS a quarantined test is dropped; a quarantined test under a selected
directory stays out through an `--ignore`; every other selected path runs
exactly as selected, so the gate still fails closed on every test that stays in
it. A quarantine outside the selection changes nothing.

`emptied` is true only when the selection was not empty and the quarantine
removed every path of it. That is the one run in which "pytest collected
nothing" is not red: the quarantine emptied it. A full run that collects
nothing, or a selection that was empty before the quarantine, stays red.

FAILURE POLICY. Pure: no I/O, no exception for any input.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class LeftOut:
    """What runs, what is ignored inside a selected directory, and whether the quarantine emptied the run."""

    paths: tuple[str, ...]
    ignores: tuple[str, ...]
    emptied: bool


def left_out(selection: Iterable[str], quarantined: Iterable[str]) -> LeftOut:
    """The selection with every quarantined test taken out of it."""
    selected = tuple(dict.fromkeys(path.strip().rstrip("/") for path in selection if path.strip()))
    out = set(quarantined)
    paths = tuple(path for path in selected if path not in out)
    ignores = tuple(sorted(
        test for test in out
        if test not in selected and any(test.startswith(f"{path}/") for path in paths)
    ))
    return LeftOut(paths=paths, ignores=ignores, emptied=bool(selected) and not paths)
