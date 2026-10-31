"""Which rows one commit touches, and therefore whose break gets replayed.

OWNS: the definition of touched.

DOES NOT OWN: replaying (`_replay.py`), or where the changed paths come from
(`git diff --cached` in the hook, the commit's own diff on the deploy VM).

TOUCHED IS WIDER THAN THE TEST FILE, and that is the point. A row is touched
when the commit changes the test, OR the module the test pins, OR the file the
break edits. The middle one is what catches a break that has stopped breaking
anything: if the module moves under a break, the change that moved it is the
change that has to answer for it, rather than a nightly run finding it later
and belonging to no commit.

WHY NOT EVERYTHING, EVERY TIME. Replaying a break costs one extra run of that
test, so the whole register is a second full suite. Per commit that is minutes
nobody has; per touched row it is seconds. Nothing here runs on a timer either:
a finding that attaches to no commit cannot be handed back by the eject, and
becomes a held deploy waiting for a person.
"""
from __future__ import annotations

from collections.abc import Sequence

from ._row import Row


def touched_by(changed: Sequence[str], rows: Sequence[Row]) -> tuple[Row, ...]:
    """Every row this commit's changed paths reach."""
    paths = tuple(path.strip() for path in changed if path and path.strip())
    return tuple(row for row in rows if _reaches(row, paths))


def _reaches(row: Row, paths: Sequence[str]) -> bool:
    """True when any changed path is the test, its module, or its break's file."""
    for path in paths:
        if path == row.test:
            return True
        if row.proved_by is not None and path == row.proved_by.file:
            return True
        if any(path == pin or path.startswith(f"{pin}/") for pin in row.pins):
            return True
    return False
