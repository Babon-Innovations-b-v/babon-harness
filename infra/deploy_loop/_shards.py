"""One gate run as one Job per shard, and the one exit code the shards add up to.

OWNS: reading `test_register --shards` output (`<shard>\\t<path>` lines) and
adding the shards' exit codes up to the code one pytest over every path would
have given.

DOES NOT OWN: which paths form a shard (`tools/test_register/_groups.py`),
making or waiting for the Jobs (`__main__.py`), or how one Job's end reads as an
exit code (`_outcome.py`).

WHY JOBS. Each shard Job asks the gate pool for its own CPU, so the pods one
commit creates are what the cluster autoscaler adds gate nodes for, up to the
pools' maximum. One Job for the whole suite runs on one node however many
there are, so a gate run did not get faster as the cluster grew.

THE EXIT CODE (0 green, 1 to 5 a run that happened and said no, anything else
could not finish):

    any shard 1 ................. 1
    any shard 2, 3 or 4 ......... the lowest of those
    any shard could not finish .. that shard's code (amber)
    every shard 5 ............... 5 (nothing collected anywhere)
    no shard at all ............. 125 (amber), never 0
    otherwise ................... 0; one shard collecting nothing is not a red
                                  while another ran tests, as one pytest over
                                  all the paths would say

It fails closed: a module group that never ran can never add up to a green.

FAILURE POLICY: pure, no I/O, no exception for any input.
"""
from __future__ import annotations

#: The code for a run that had no shard to answer for it; amber.
RC_NO_SHARD = 125
_SAID_NO = (2, 3, 4)
_VERDICTS = (0, 1, 2, 3, 4, 5)


def read_shards(text: str) -> list:
    """`<shard>\\t<path>` lines as (shard, paths) pairs, in first-seen order."""
    order: dict = {}
    for line in text.splitlines():
        name, sep, path = line.partition("\t")
        if sep and name.strip() and path.strip():
            order.setdefault(name.strip(), []).append(path.strip())
    return list(order.items())


def combined_rc(codes: list) -> int:
    """The one exit code a run's shards add up to (the table in the module docstring)."""
    if not codes:
        return RC_NO_SHARD
    if 1 in codes:
        return 1
    said_no = [code for code in codes if code in _SAID_NO]
    if said_no:
        return min(said_no)
    unfinished = [code for code in codes if code not in _VERDICTS]
    if unfinished:
        return unfinished[0]
    if all(code == 5 for code in codes):
        return 5
    return 0
