"""A worklist item a person asked for never tells the brief it is not news.

WHAT IT PINS. `state.worklist.render`, the block the brief and the advisor
read through `manage_worklist list`: an item owned by a person that has sat
still reads "unchanged for N days, still open", while a watch the assistant opened
itself still reads "so it is not news". Otherwise the brief could drop an
item a person asked for because its line said "not news", while the
advisor, reading the same item, tells them to chase it.
`owner` is who asked for the item, not who it waits on, so no line may claim
the item is waiting on its owner: a look_into the owner asked the assistant to carry is
The assistant's job, not the owner's.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The age is set
by hand on the row, fourteen days back, and the owner is the registry spelling
the item was filed under. Nothing is asserted about how often the brief raises
the item, only what the block says about it.
"""
from __future__ import annotations

import datetime as _datetime

import pytest

from apps.assistant.core import state
from apps.assistant.core.state.conn import get_connection

_TITLES = ("Chase Example Printers", "Find out why the GPU node cost rose", "Registry tag count")


@pytest.fixture()
def lines(monkeypatch: pytest.MonkeyPatch, tmp_path) -> dict[str, str]:
    """The rendered line of each item, by title, in a database of its own."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    state.reset_for_tests()
    state.worklist.add_item("watch", _TITLES[0], owner="Alex")
    state.worklist.add_item("look_into", _TITLES[1], owner="Alex")
    state.worklist.add_item("watch", _TITLES[2], owner="assistant")
    fortnight = (
        _datetime.datetime.now(_datetime.timezone.utc) - _datetime.timedelta(days=14)
    ).isoformat()
    with get_connection() as conn:
        conn.execute("UPDATE worklist SET updated_at = ?", (fortnight,))
        conn.commit()
    rendered = state.worklist.render().splitlines()[1:]
    return {title: next(line for line in rendered if title in line) for title in _TITLES}


def test_a_watch_a_person_asked_for_is_still_open(lines: dict[str, str]) -> None:
    """the owner's quiet watch is still open, and the assistant's own quiet watch is not news."""
    assert "not news" not in lines["Chase Example Printers"]
    assert "unchanged for 14 days, still open" in lines["Chase Example Printers"]
    assert "not news" in lines["Registry tag count"]


def test_a_look_into_a_person_asked_for_never_blames_them(lines: dict[str, str]) -> None:
    """A look_into the owner asked the assistant to carry is the assistant's job, never waiting on the owner."""
    line = lines["Find out why the GPU node cost rose"]
    assert "waiting on" not in line
    assert "not news" not in line
