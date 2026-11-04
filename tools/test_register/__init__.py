"""One row per test, and everything that reads it.

Every test in this repository has one row in `_rows.py`. A row says which
module the test pins, which changed paths select it, and the break that proves
it can fail. Two things read the register:

  `tools/gate_scope/select.py`  takes `runs_when` to narrow the deploy gate;
  `.claude/hooks/pre-commit`    refuses a commit the register and the tree
                                disagree about, and replays the break of every
                                row the commit touches.

The deploy gate also writes one field of a row, `quarantined` (`_row.py`): a
test it found to be the wrong one, left out of the gate until its owner fixes
it.

Why it exists: a test that can never fail looks exactly like a good one. It is
green, it is named for an invariant, and it verifies nothing. Writing the break
down beside the test, and replaying it whenever the test or its module changes,
is what keeps the suite honest.

Sealed seam: the names in `__all__` are the whole public surface.
"""
from __future__ import annotations

from ._break import Break
from ._check import check
from ._coverage import uncovered
from ._groups import module_groups
from ._level import group_key, level_of
from ._modules import modules_in
from ._owner import owner_login, quarantine_issue, quarantine_note
from ._quarantine import LeftOut, left_out
from ._replay import replay
from ._row import Row, gate_quarantines, quarantined_tests, quarantines_added, with_quarantine
from ._rows import ROWS
from .birth import Pin, live_reads, pin_drift, read_pin, scaffold, sealed_argv
from ._touched import touched_by
from ._triggers import triggers_for

__all__ = [
    "ROWS",
    "Break",
    "LeftOut",
    "Pin",
    "Row",
    "check",
    "gate_quarantines",
    "group_key",
    "level_of",
    "module_groups",
    "left_out",
    "live_reads",
    "modules_in",
    "owner_login",
    "pin_drift",
    "quarantine_issue",
    "quarantine_note",
    "quarantined_tests",
    "quarantines_added",
    "read_pin",
    "replay",
    "scaffold",
    "sealed_argv",
    "touched_by",
    "triggers_for",
    "uncovered",
    "with_quarantine",
]
