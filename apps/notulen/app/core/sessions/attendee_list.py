"""One name per person in an attendee list, whatever case it arrived in.

The same person can arrive twice when their name differs only in case
(``['alice', 'bob', 'Bob']`` for a two-person meeting). The list is read
twice over, so one duplicate costs twice: the minutes header names Bob twice,
and the GPU worker, which caps diarization at the number of attendees, lets
the recording split into three voices instead of two.

The order the names arrived in is kept, because people read this list. Where
two spellings of one name arrive, the capitalised one is kept.

FAILURE POLICY: pure list work, no I/O, nothing to swallow.
"""
from __future__ import annotations


def clean_attendees(names: list[str] | None) -> list[str]:
    """The same people, each named once. Empty in, empty out."""
    kept: dict[str, str] = {}
    for name in names or []:
        spelling = " ".join(str(name).split())
        if not spelling:
            continue
        person = spelling.casefold()
        if person not in kept or _reads_better(spelling, kept[person]):
            kept[person] = spelling
    return list(kept.values())


def _reads_better(candidate: str, current: str) -> bool:
    """A name that starts with a capital reads better than one that does not."""
    return candidate[:1].isupper() and not current[:1].isupper()
