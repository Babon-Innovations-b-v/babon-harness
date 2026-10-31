"""An item the assistant booked to itself is still told once per reader.

WHAT IT PINS. `message_teammate.execute` with `manage_worklist`, at their public
seams: a worklist item opened under the assistant's own name (owner "assistant", which is
what the door books since `requested_by: "the assistant"` was accepted) counts in the
already-told ledger for whoever is told about it. The second unmoved telling to
the same person is refused, and telling one person does not silence the
telling to another.

WHY IT EXISTS. The ledger matched only items the RECIPIENT owns. While the
door held humans only, the brief booked everything to the owner, so the catering
question was the owner's and was matched. Once the door let the
brief book what nobody asked for to the assistant, every such item would have had
owner "assistant", and every ask about it would have skipped the ledger and been sent again
unchanged.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From the
ledger's published rule ("same fingerprint as yesterday may not be narrated
again") and from what a person would see: the owner asked the same unchanged
question twice gets it once; a teammate, never told, gets it the first time.
"""
from __future__ import annotations

import pytest

from apps.assistant.core import state
from apps.assistant.core.tools.meta import manage_worklist
from apps.assistant.core.tools.team import message_teammate

_CONTRACT_TITLE = "Issue 47 catering: the caterer's price per head"
_ASK = "catering 47 needs your ask to Jordan: the caterer's price per head."


@pytest.fixture()
def sent(monkeypatch: pytest.MonkeyPatch, tmp_path) -> list[tuple[str, str]]:
    """A real state database, and every Signal send recorded instead of sent."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    state.reset_for_tests()
    calls: list[tuple[str, str]] = []

    def _send(subject: str, message: str, recipient: str = "") -> bool:
        calls.append((recipient, message))
        return True

    numbers = {"alex": "+15550100012", "sam": "+15550100013"}
    monkeypatch.setenv(message_teammate._ENABLE_ENV, "1")
    monkeypatch.setattr(message_teammate._signal, "send", _send)
    monkeypatch.setattr(message_teammate.people, "number_for", lambda p: numbers[p.lower()])
    monkeypatch.setattr(message_teammate.people, "language_for", lambda p: "en")
    monkeypatch.setattr(message_teammate._quiet_hours, "quiet_now", lambda: False)
    monkeypatch.setattr(message_teammate._state, "recent_chat_turns", lambda *a, **k: [])
    monkeypatch.setattr(message_teammate.write_guard, "audit", lambda *a, **k: None)
    monkeypatch.setattr(message_teammate, "_issue_facts", lambda number: "OPEN|4|2/5")
    return calls


def _book_to_assistant() -> None:
    """Open the catering question the way a door write booked to the assistant does."""
    answer = manage_worklist.execute(
        {"action": "add", "kind": "question", "title": _CONTRACT_TITLE}, owner="assistant"
    )
    assert answer.startswith("tracking as worklist item"), answer


def _tell(person: str) -> str:
    return message_teammate.execute({"person": person, "message": _ASK}, actor="assistant")


def test_the_second_ask_to_alex_about_a_assistant_item_is_refused(
    sent: list[tuple[str, str]],
) -> None:
    """The bug: the assistant's own item never reached the ledger, so the ask repeated."""
    _book_to_assistant()
    first = _tell("Alex")
    assert not first.startswith("not sent:"), first
    second = _tell("Alex")
    assert second.startswith("not sent:"), second
    assert len(sent) == 1, sent


def test_telling_alex_does_not_silence_telling_sam(
    sent: list[tuple[str, str]],
) -> None:
    """The dangerous direction: one reader's telling must not count for another."""
    _book_to_assistant()
    _tell("Alex")
    answer = _tell("Sam")
    assert not answer.startswith("not sent:"), answer
    assert [recipient for recipient, _ in sent] == ["+15550100012", "+15550100013"]
