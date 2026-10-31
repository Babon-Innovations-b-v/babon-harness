"""The part of a notulen filename that says who was in the meeting.

One set of people makes one name, whatever order the attendee list arrived in
and whether the sign-on handed over full names or somebody typed first names
into the dashboard: names are cut to the first word, lowercased, deduplicated
and sorted, so ``Alice Example, Bob`` and ``bob, alice`` both give
``alice_bob``. That is the whole point of sorting: the folder groups by who
was there, which only works if one pair of people cannot make two names.
"""
from __future__ import annotations

from apps.notulen.app.shared.slug import slugify

# past this the filename stops being a name and starts being a list
MAX_NAMES_IN_A_FILENAME = 3


def attendee_name(attendees: list[str]) -> str:
    """``alice_bob``, or ``alice_bob_carol_plus1``; empty when nobody is named.

    An empty return is the caller's signal to fall back to the meeting title,
    because losing the minutes over an empty attendee list is not an option.
    """
    first_names = sorted({
        slugified
        for slugified in (
            slugify(person.split()[0]) for person in attendees if person.split()
        )
        if slugified
    })
    if not first_names:
        return ""
    if len(first_names) <= MAX_NAMES_IN_A_FILENAME:
        return "_".join(first_names)
    shown = "_".join(first_names[:MAX_NAMES_IN_A_FILENAME])
    return f"{shown}_plus{len(first_names) - MAX_NAMES_IN_A_FILENAME}"
