"""A page held by quiet hours shows in `my_actions` as waiting.

WHAT IT PINS. `my_actions.execute`, the door read the chat checks before saying
whether something reached it, over the two tables that hold what has not been
sent: `notify_pen` (a ping waiting for the flush) and `page_hold` (a written
page waiting for quiet hours or the morning gate). While either holds a batch
done, asking about it answers "held", and once both have let it go the answer
no longer says so.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The ping is a
nightly batch done that arrives at 22:03 and goes out at 08:00 the next
morning. Nothing was sent in between, so the only true answer
while it waits is that it is held; the test reads that off the words "held in
the pen" and "held to send", which it does not share with any sent line.
"""
from __future__ import annotations

import pytest

from apps.assistant.core import state
from apps.assistant.core.tools.meta import my_actions

_DONE = "batch done [nightly], all clear"


@pytest.fixture()
def held(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """The batch done held twice, once in the pen and once as a page."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    state.reset_for_tests()
    state.enqueue_ping(_DONE, "dispatched=21, completed=21, failed=0", "notify")
    state.hold_page(f"{_DONE}. At 22:03.", road="pen", subject="the night")


def test_a_held_batch_done_answers_held_not_absent(held) -> None:
    answer = my_actions.execute({"about": "batch done"})

    assert not answer.startswith("no actions"), answer
    assert f"held in the pen -> {_DONE}" in answer, answer
    assert "held to send -> the night" in answer, answer


def test_once_sent_it_is_no_longer_shown_as_waiting(held) -> None:
    state.mark_flushed([ping["id"] for ping in state.unflushed_pings()])
    state.mark_released([page["id"] for page in state.pending_pages()])

    answer = my_actions.execute({"about": "batch done"})

    assert "held" not in answer, answer
