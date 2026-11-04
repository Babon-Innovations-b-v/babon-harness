"""One row per test, and everything that reads it.

Every test in this repository has one row in `_rows.py`. A row says which
module the test pins, which changed paths select it, and the break that proves
it can fail. Two things read the register:

  `tools/gate_scope/select.py`  takes `runs_when` to narrow the deploy gate;
  `.claude/hooks/pre-commit`    refuses a commit the register and the tree
                                disagree about, and replays the break of every
                                row the commit touches.

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
from ._replay import replay
from ._row import Row
from ._rows import ROWS
from ._scaffold import scaffold
from ._touched import touched_by
from ._triggers import triggers_for

__all__ = [
    "ROWS",
    "Break",
    "Row",
    "check",
    "group_key",
    "level_of",
    "module_groups",
    "modules_in",
    "replay",
    "scaffold",
    "touched_by",
    "triggers_for",
    "uncovered",
]
