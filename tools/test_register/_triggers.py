"""The changed-path globs that select one test.

OWNS: the lookup the deploy gate's selector does once per floor test.

DOES NOT OWN: the rows (`_rows.py`), or what the selector does with the answer
(`gate_scope/select.py`).

WHAT `None` MEANS, and it is the opposite of an empty tuple. `None` is "this
test has no row", and `gate_scope/_narrowed_floor` keeps such a test on every
selected cycle, which is the safe direction. An empty tuple would be "this test
is selected by nothing", which no row is allowed to say: a test nothing selects
is a test that never runs, and the register refuses one at check time.

Triggers are GLOBS, never bare prefixes: a prefix trigger of a top directory
makes a Caddyfile select a test that only ever reads `.py` files.
"""
from __future__ import annotations

from ._rows import ROWS

#: Built once at import. The register is a literal, so this cannot go stale
#: inside a process, and the gate builds a fresh one every cycle anyway.
_BY_TEST = {row.test: row.runs_when for row in ROWS}


def triggers_for(test: str) -> tuple[str, ...] | None:
    """The globs that select this test, or `None` when it has no row."""
    return _BY_TEST.get(test)
