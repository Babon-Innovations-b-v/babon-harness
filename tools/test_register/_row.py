"""One test, and everything the machine needs to know about it.

OWNS: the shape of a register row.

DOES NOT OWN: the rows themselves (`_rows.py`), what fires a row
(`gate_scope/select.py` reads `runs_when`), or whether a row's break still
breaks anything (`_replay.py`).

THE FIELDS, and why each is here rather than derived.

`test` is the file. It is the key: one row per test file, never per module,
because a module can need more than one test once the tests that prove two
modules still work together are counted.

`pins` is the module or modules the test covers. One name is the ordinary
case; two or more makes it an integration test, and that is the whole
declaration. Nothing derives this: an import closure says which files a test
can reach, which is a wider and different question, and the tests that read
the tree as text import nothing at all.

`runs_when` is the changed-path globs that select this test. Globs, never bare
prefixes: a prefix trigger of a top directory makes every file under it, a
Caddyfile included, select a test that only ever reads `.py` files.

`proved_by` is the break, and it may be `None` only while a test is being
written. `__main__.py --check` refuses a committed row without one.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ._break import Break


@dataclass(frozen=True)
class Row:
    """What the register knows about one test file."""

    test: str
    pins: tuple[str, ...]
    runs_when: tuple[str, ...]
    proved_by: Break | None = None
    note: str = ""
    kind: str = field(default="module")
