"""A send that lists a worklist item is counted as a telling of it, even when it names no issue number.

WHAT IT PINS. `message_teammate.execute`, at its public seam: an id passed in
`worklist_items` makes that open item one the message is about, so a delivered
send moves the ledger's count for it exactly as an issue number in the text
would.

WHY IT EXISTS. A chase message can name a vendor such as "Example Printers"
and no issue number. The ledger only matched on issue numbers, so such a
telling was never counted: an item read as told once while the owner had been
told twice, and the escalation threshold could never be reached.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From the
ledger's published rule that a delivered send counts once per item it is
about: one prior telling under a different fingerprint, plus this send, is 2.
The message text is a short advisor chase, under the word cap.
"""
from __future__ import annotations

import pytest

from apps.assistant.core import state
from apps.assistant.core.tools.team import message_teammate

_PRINTER = "Issue 7: Example Printers quote for an event, deadline end of October"
_CHASE = (
    "Example Printers never answered your 28 Sep quote request. Chase them "
    "or switch printer: this week."
)


@pytest.fixture()
def sent(monkeypatch: pytest.MonkeyPatch, tmp_path) -> list[str]:
    """A real state database, and every Signal send recorded instead of sent."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    state.reset_for_tests()
    calls: list[str] = []

    def _send(subject: str, message: str, recipient: str = "") -> bool:
        calls.append(message)
        return True

    monkeypatch.setenv(message_teammate._ENABLE_ENV, "1")
    monkeypatch.setattr(message_teammate._signal, "send", _send)
    monkeypatch.setattr(message_teammate.people, "number_for", lambda p: "+15550100010")
    monkeypatch.setattr(message_teammate.people, "language_for", lambda p: "en")
    monkeypatch.setattr(message_teammate._quiet_hours, "quiet_now", lambda: False)
    monkeypatch.setattr(message_teammate._state, "recent_chat_turns", lambda *a, **k: [])
    monkeypatch.setattr(message_teammate.write_guard, "audit", lambda *a, **k: None)
    monkeypatch.setattr(message_teammate, "_issue_facts", lambda number: "OPEN|3|0/0")
    return calls


def _count(item_id: int) -> int:
    key = state.reported_items.worklist_key(item_id)
    return state.reported_items.tellings([key]).get(key, ("", 0))[1]


def test_the_listed_item_is_counted(sent: list[str]) -> None:
    item_id = state.worklist.add_item("watch", _PRINTER, owner="Alex")
    state.reported_items.mark_reported(
        [state.reported_items.Candidate(f"worklist:{item_id}", "told-earlier")]
    )
    answer = message_teammate.execute(
        {"person": "Alex", "message": _CHASE, "worklist_items": [item_id]},
        actor="assistant",
    )
    assert answer == "messaged Alex.", answer
    assert len(sent) == 1
    assert _count(item_id) == 2, "the chase went out and the ledger never saw it"


def test_no_list_and_no_number_still_sends(sent: list[str]) -> None:
    """The list is optional: without it the message goes out as before."""
    item_id = state.worklist.add_item("watch", _PRINTER, owner="Alex")
    answer = message_teammate.execute(
        {"person": "Alex", "message": _CHASE, "worklist_items": ["not a number"]},
        actor="assistant",
    )
    assert answer == "messaged Alex.", answer
    assert _count(item_id) == 0
