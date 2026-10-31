"""The edit that proves one test can fail.

OWNS: the shape of a break, and nothing else. It is data: a file, an exact
substring of that file, what that substring becomes, and one sentence saying
which assertion the change trips.

DOES NOT OWN: applying it (`_replay.py`), or deciding whether a row needs one
(`_row.py` says a row may carry none, `__main__.py --check` says when that is
refused).

WHY A LITERAL REPLACE AND NOT A DIFF. A unified diff carries line numbers, and
a line number goes stale the moment anything above it moves, which turns every
unrelated edit into a broken break. An exact substring survives that: it breaks
only when the line it names actually changes, and then the break SHOULD be
re-examined, because the code it was proving is the code that moved.

`old` must appear exactly once in `file`. Two occurrences is refused rather
than guessed at: replacing the wrong one proves nothing and the test would go
red for a reason nobody wrote down.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Break:
    """A realistic fault, and the sentence saying what it costs."""

    file: str
    old: str
    new: str
    why: str
