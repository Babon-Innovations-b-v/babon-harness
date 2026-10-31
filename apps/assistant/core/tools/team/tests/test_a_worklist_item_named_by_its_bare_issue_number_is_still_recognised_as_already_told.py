"""A worklist item named by its bare issue number is still recognised as already told.

WHAT IT PINS. `message_teammate.execute`, at its public seam: a message that
names one of the reader's open worklist items as "catering 47", with no "#" and no
"issue", counts as a telling of that item exactly like "#47" does, so a second
telling with nothing moved is refused.

WHY IT EXISTS. People name an issue by its bare number as often as with a
"#". A matcher that only knows "#47" and "issue 47" misses a message that
writes "catering 47", so the same ask goes out again with nothing moved.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From the
ledger's published rule, "same fingerprint as yesterday may not be narrated
again", and from reading the message as a person would: "catering 47" names the
item whose title is "Issue 47 catering: ...". The two message texts are two
wordings of one ask. The other half is that a number inside
an amount ("EUR 1.500") is not an issue number, so it must not match an item
whose issue happens to be 132.
"""
from __future__ import annotations

import pytest

from apps.assistant.core import state
from apps.assistant.core.tools.team import message_teammate

_CONTRACT_TITLE = "Issue 47 catering: the caterer's price per head"
_FIRST_ASK = "catering 47 needs your ask to Jordan: the caterer's price per head."
_SECOND_ASK = "catering 47's decisive number is still unanswered. Ask Jordan today."


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
    monkeypatch.setattr(message_teammate, "_issue_facts", lambda number: "OPEN|0|0/0")
    return calls


def _tell(message: str) -> str:
    return message_teammate.execute({"person": "Alex", "message": message}, actor="Alex")


def test_a_second_catering_47_ask_is_refused(sent: list[str]) -> None:
    """The bug: the same ask, spelled without '#', went out again."""
    state.worklist.add_item("question", _CONTRACT_TITLE, owner="Alex")
    first = _tell(_FIRST_ASK)
    assert not first.startswith("not sent:"), first
    second = _tell(_SECOND_ASK)
    assert second.startswith("not sent:"), second
    assert len(sent) == 1, "the bare-number re-ask went out anyway"


def test_a_number_inside_an_amount_is_not_an_issue(sent: list[str]) -> None:
    """'EUR 1.500' is money, so it is no telling of the item for issue 132."""
    state.worklist.add_item("watch", "Issue 132: unrelated", owner="Alex")
    _tell("The team day budget totals EUR 1.500 so far.")
    answer = _tell("The team day budget still totals EUR 1.500.")
    assert not answer.startswith("not sent:"), answer
    assert len(sent) == 2
