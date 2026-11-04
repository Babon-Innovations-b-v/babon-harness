"""The tests that were already over a one-test rule the day it arrived.

OWNS: the known debt, listed once so main stayed green the day each rule
arrived. Data only. Two lists: `DEBT` (a level with more than one test) and
`FUNCTION_DEBT` (a file with more than one test function). Each only shrinks.

Each `DEBT` entry is the level (module, module group, or declared unit) the
test was counted against that day, and the test file. `_second.py` matches by
the test file alone, so the level is there for the reader and for whoever folds
each level's entries into its one test, keeping every check they make, and
deletes them here. Nothing joins either list: a row that is not on it and is
not the only test of its level is refused, and an entry whose test is gone is
refused too, so the lists only shrink.
"""
from __future__ import annotations

#: 127 tests over 18 levels on the day the rule arrived. Only ever delete.
DEBT: tuple[tuple[str, str], ...] = (
)

#: 108 files holding more than one test function that day, each with its
#: count. A file may not grow past its count; one that shrank lowers its entry,
#: and one down to a single test loses it. Only ever shrink.
FUNCTION_DEBT: tuple[tuple[str, int], ...] = (
)
