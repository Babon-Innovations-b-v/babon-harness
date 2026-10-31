"""A look_into nobody has answered is rendered as work to do, never as not news.

WHAT IT PINS. `worklist.render`, at its public seam: an open look_into older
than a day ends in a clause asking for the next step, aged from when it was
opened, while a watch that has sat still keeps its "unchanged for N days" label.

WHY IT EXISTS. The block put "unchanged for N days, so it is not news" on every
kind of item. For a watch that is right; for a look_into it read as an
instruction to skip it. An item could sit for weeks with that label, and
another could gather reworded restatements, each of which moved
`updated_at`, so it never even got a label.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From what the
two kinds mean in the module docstring: a watch is checked and reported when it
changes, a look_into is pursued until it has an answer. Five days still is past
both thresholds; a look_into opened a day ago and restated twice today has a
fresh `updated_at` but is a day open by its `created_at`.
"""
from __future__ import annotations

import datetime as _datetime

import pytest

from apps.assistant.core import state


@pytest.fixture()
def db(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    state.reset_for_tests()


def _backdate(item_id: int, days: int, *, also_updated: bool) -> None:
    then = (
        _datetime.datetime.now(_datetime.timezone.utc) - _datetime.timedelta(days=days)
    ).isoformat()
    column_sql = "created_at = ?, updated_at = ?" if also_updated else "created_at = ?"
    params = (then, then, item_id) if also_updated else (then, item_id)
    with state.conn.get_connection() as conn:
        conn.execute(f"UPDATE worklist SET {column_sql} WHERE id = ?", params)
        conn.commit()


def _line(item_id: int) -> str:
    return next(
        line for line in state.worklist.render().splitlines()
        if line.startswith(f"- [{item_id}]")
    )


def test_a_stalled_look_into_asks_for_the_next_step(db: None) -> None:
    probe = state.worklist.add_item("look_into", "Find what stopped the probe side")
    watched = state.worklist.add_item("watch", "Issue 27", owner="Robin")
    _backdate(probe, 5, also_updated=True)
    _backdate(watched, 5, also_updated=True)

    probe_line = _line(probe)
    assert "not news" not in probe_line, (
        f"an unanswered look_into was labelled as something to skip: {probe_line}"
    )
    assert "take the next step" in probe_line, probe_line
    assert _line(watched).endswith("unchanged for 5 days, still open"), (
        "a quiet watch lost its label"
    )


def test_restating_the_symptom_does_not_hide_it(db: None) -> None:
    probe = state.worklist.add_item("look_into", "Find what stopped the probe side")
    _backdate(probe, 1, also_updated=False)
    state.worklist.record_progress(probe, "Blind spot persists.")
    state.worklist.record_progress(probe, "Probe side still at up 0; blind spot persists.")
    assert "take the next step" in _line(probe), (
        "a reworded restatement moved updated_at and the look_into went unlabelled"
    )


def test_a_look_into_opened_today_carries_no_nudge(db: None) -> None:
    probe = state.worklist.add_item("look_into", "Find what stopped the probe side")
    assert "take the next step" not in _line(probe)
