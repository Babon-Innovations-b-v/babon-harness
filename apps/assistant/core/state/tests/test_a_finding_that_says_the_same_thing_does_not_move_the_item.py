"""Checking an item is not the same event as the item changing.

WHAT IT PINS. `worklist.record_progress`, at its public seam: a finding whose
material state matches the one already stored stamps `last_checked_at` and
leaves `last_finding` and `updated_at` alone, and returns False. A finding that
says something new moves all three and returns True.

WHY IT EXISTS. Without it the two columns collapse into one. Patrol runs
several times a day and writes a finding on every open item on every pass, and
each finding opens with the moment it looked, because the doctrine asks for a
zone on a reported time. If every finding moved the item, every open item would
read "0 days since it moved", even one unchanged for a month, and anything
asking "has this moved" would be reading a clock.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From what the
two column names mean, not from what the function currently does: one records
that somebody looked, the other records that the thing changed. So a repeated
finding must move exactly one of them, and the test asserts on the stored row
rather than on the return value alone. The two findings in the first case are
real strings off the container, two hours apart in stamp and identical in meaning.

THE DANGEROUS DIRECTION IS A LOST FINDING, so the second case asserts that real
news still lands: an item that genuinely moved must overwrite the finding, or
this change would quietly drop what the assistant learned.
"""
from __future__ import annotations

import pytest

from apps.assistant.core import state

_ELEVEN = (
    "2026-09-16 11:00 local time (CEST): Issue 27 still open, "
    "0 comments. Assigned to Robin, no activity. Unchanged."
)
_THIRTEEN = (
    "2026-09-16 13:00 local time (CEST): Issue 27 still open, "
    "0 comments. Assigned to Robin, no activity. Unchanged."
)


@pytest.fixture()
def item(monkeypatch: pytest.MonkeyPatch, tmp_path) -> int:
    """One open item in a database of its own."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    state.reset_for_tests()
    return state.worklist.add_item("watch", "Issue 27: backup restore test", owner="Robin")


def _row(item_id: int) -> dict:
    return next(row for row in state.worklist.open_items() if row["id"] == item_id)


def test_a_restamped_finding_does_not_move_the_item(item: int) -> None:
    """The churn. Two patrol passes, one meaning, one stored finding."""
    assert state.worklist.record_progress(item, _ELEVEN) is True
    after_first = _row(item)

    assert state.worklist.record_progress(item, _THIRTEEN) is False
    after_second = _row(item)

    assert after_second["last_finding"] == _ELEVEN, (
        "a re-stamped finding overwrote the stored one, so the item reads as "
        "news on every patrol pass"
    )
    assert after_second["updated_at"] == after_first["updated_at"], (
        "updated_at moved for an item that did not change, which is what made "
        "it useless as a signal"
    )


def test_checking_is_still_recorded(item: int) -> None:
    """Quiet is not the same as unwatched: somebody did look."""
    state.worklist.record_progress(item, _ELEVEN)
    first = _row(item)["last_checked_at"]
    state.worklist.record_progress(item, _THIRTEEN)
    assert _row(item)["last_checked_at"] != first, (
        "the pass that found nothing new was not recorded at all, so the item "
        "looks unwatched rather than unchanged"
    )


def test_the_block_says_how_long_an_item_has_sat_still(item: int) -> None:
    """The point of fixing the column: a reader can see quiet from unwatched.

    Rendered by hand at a date far enough ahead that the item is quiet, since
    the alternative is a test that waits two days.
    """
    state.worklist.record_progress(item, _ELEVEN)
    fresh = state.worklist.render()
    assert "unchanged for" not in fresh, (
        f"an item that moved just now was called stale: {fresh}"
    )
    assert state.worklist._days_still("2026-01-01T00:00:00+00:00") > 200, (
        "an old stamp did not read as old, so the line can never appear"
    )
    assert state.worklist._days_still(None) == 0, (
        "an unreadable stamp must read as quiet, not as ancient"
    )


def test_real_news_still_lands(item: int) -> None:
    """The other half. A finding that says something new overwrites."""
    state.worklist.record_progress(item, _ELEVEN)
    moved = state.worklist.record_progress(
        item,
        "2026-09-16 17:00 local time (CEST): Issue 27 now has 2 "
        "comments and Robin has started.",
    )
    assert moved is True
    assert "2 comments" in _row(item)["last_finding"], (
        "a finding that genuinely moved was dropped"
    )
