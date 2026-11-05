"""Minutes land in a month folder named by who was there, whatever order the names came in.

WHAT IT PINS. `publish.github.target_path`, the path grammar every committed
set of minutes follows: `<NOTULEN_TARGET_PATH>/<YYYY-MM>/<who>/<YYYY-MM-DD>.md`,
where `who` is the attendees' first names, lowercased, deduplicated, sorted and
capped at three with a `_plusN` tail, falling back to the meeting title
slugged (lowercase, spaces as underscores).

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Each path is
assembled by hand from the made-up date, title and names: take the date's
first ten characters, cut each name to its first word, sort, keep three and
count the rest.

ONE FUNCTION. This module's one test. A new check is a parametrized case of
it, never a second function.

WHAT IT WAS PROVED AGAINST. The break in this test's register row stops
sorting the names, so the two orderings of one pair name two folders.

GUARDS. One test per module (#1210), 2026-11-05.
"""
from __future__ import annotations

import pytest

from apps.notulen.app.core.publish.github.target_path import target_path

CASES = [
    pytest.param("2026-05-04", "Weekly", ["Sam Example", "alex"], "minutes/2026-05/alex_sam/2026-05-04.md",
                 id="first-names-sorted"),
    pytest.param("2026-05-04T09:30:00+02:00", "Weekly", ["alex", "Sam"], "minutes/2026-05/alex_sam/2026-05-04.md",
                 id="the-other-order-is-the-same-folder"),
    pytest.param("2026-05-04", "Weekly", ["Sam", "sam example"], "minutes/2026-05/sam/2026-05-04.md",
                 id="one-person-once"),
    pytest.param("2026-12-31", "Weekly", ["Robin", "Kim", "Alex", "Sam", "Dee"],
                 "minutes/2026-12/alex_dee_kim_plus2/2026-12-31.md", id="three-names-then-a-count"),
    pytest.param("2026-05-04", "Board Review", [], "minutes/2026-05/board_review/2026-05-04.md",
                 id="nobody-named-falls-back-to-the-title"),
]


@pytest.mark.parametrize("meeting_date, title, attendees, expected", CASES)
def test_minutes_land_in_a_month_folder_named_by_who_was_there_whatever_order_the_names_came_in(
        meeting_date: str, title: str, attendees: list, expected: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The path is the hand-assembled one."""
    monkeypatch.setenv("NOTULEN_TARGET_PATH", "/minutes/")
    assert target_path(meeting_date, title, attendees) == expected
