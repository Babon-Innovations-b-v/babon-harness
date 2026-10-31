"""A teammate message about a worklist item reaches the relay as concerning that item.

WHAT IT PINS. `message_teammate.execute` with `worklist_items`, then
`core.sent_feed.sends_after`, the read behind `GET /relay/sent`, and
`openclaw_watch.chat_relay.note`, which turns one send into the text the
gateway's chat session reads. All over a temporary state DB.

WHY IT EXISTS. A reply closes a question only through `record_answer`, which
needs the worklist item's id. Handing the chat the recipient's whole open
list leaves it to guess which item a reply answers, and a guess it does not
make means `record_answer` is not called. So a send that knows its item says so.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The caller
names the item, so the item is known before anything runs: the message lists
The owner's key-rotation item, and the owner's other open item is not what it is about.
The note must name the one item and the record_answer call for it, and must
not hand over the list.
"""
from __future__ import annotations

import pytest

from apps.assistant.watch import chat_relay
from apps.assistant.core import sent_feed, state
from apps.assistant.core.tools.team import message_teammate

_ALEX = "+15550100012"


@pytest.fixture()
def sent(monkeypatch: pytest.MonkeyPatch, tmp_path) -> list[str]:
    """A real state database, the owner in the registry, and Signal recorded instead of sent."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("SIGNAL_PEOPLE", f"{_ALEX}=Alex:founder:{_ALEX}")
    state.reset_for_tests()
    calls: list[str] = []

    def _send(subject: str, message: str, recipient: str = "") -> bool:
        calls.append(message)
        return True

    monkeypatch.setenv(message_teammate._ENABLE_ENV, "1")
    monkeypatch.setattr(message_teammate._signal, "send", _send)
    monkeypatch.setattr(message_teammate.people, "number_for", lambda person: _ALEX)
    monkeypatch.setattr(message_teammate.people, "language_for", lambda person: "en")
    monkeypatch.setattr(message_teammate._quiet_hours, "quiet_now", lambda: False)
    monkeypatch.setattr(message_teammate._state, "recent_chat_turns", lambda *a, **k: [])
    monkeypatch.setattr(message_teammate.write_guard, "audit", lambda *a, **k: None)
    return calls


def test_a_message_listing_its_item_reaches_the_relay_as_concerning_that_item(sent: list[str]) -> None:
    """The note names the listed item and the call that records a reply to it, and no list."""
    rotation = state.worklist.add_item("question", "Rotate the Anthropic key", owner="Alex")
    other = state.worklist.add_item("watch", "Nightly backup size", owner="Alex")
    answer = message_teammate.execute(
        {
            "person": "Alex",
            "message": "Did you rotate the Anthropic key yet?",
            "worklist_items": [rotation],
        },
        actor="assistant",
    )
    assert answer == "messaged Alex.", answer

    send = sent_feed.sends_after(0).sends[0]
    assert [item["id"] for item in send["concerns"]] == [rotation], (
        f"the send concerns {send['concerns']}; it must concern item {rotation} only"
    )
    assert send["open_items"] == [], "a send that knows its item must not also hand over the list"
    note = chat_relay.note(send)
    assert f"record_answer with item_id {rotation}" in note, f"the note names no call: {note!r}"
    assert f"[{other}]" not in note, f"the note offers item {other} as well: {note!r}"
