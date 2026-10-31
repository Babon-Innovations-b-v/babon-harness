"""A question asked again after the assistant only reworded its own finding is refused.

WHAT IT PINS. `message_teammate.execute` together with `manage_worklist`, at
their public seams: once a person has been asked about an open worklist item of
theirs, writing a new sentence on that row with `manage_worklist progress` does
not make the same ask sendable again. Only a fact from outside the assistant does: the
issue the item names gaining a comment or a ticked box, or the row closing.

WHY IT EXISTS. An ask repeated morning after morning is the shape this
stops. Each morning's brief can send the ask and then record a fresh
paraphrase on the row ("the owner met Jordan, no update posted"), as actor
the owner, through the door. A ledger that fingerprints that
paraphrase reads the next morning as news.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From what a
person would see: nothing about the item changed between the asks except words
the assistant wrote about it, so a colleague would ask once and wait. The sequence is
an ask followed by the brief's own progress note, five times, so
one message goes out and four are refused. Then the owner comments on the issue,
which is an answer, and the next ask is a new one.
"""
from __future__ import annotations

import pytest

from apps.assistant.core import state
from apps.assistant.core.tools.meta import manage_worklist
from apps.assistant.core.tools.team import message_teammate

_CONTRACT_TITLE = "Issue 47 catering: the caterer's price per head for the team day"
_ASKS = (
    "Alex, ask Jordan what the caterer's price per head is for #47.",
    "Did Jordan give the caterer's price for issue 47 yet? Put the number on the issue.",
    "catering 47 needs your ask to Jordan.",
    "#47: the price per head is still missing.",
    "catering 47's decisive number is still unanswered.",
)
_PROGRESS_NOTES = (
    "Asked Alex to chase Jordan for the caterer's price.",
    "Still not recorded. Asked Alex twice.",
    "Alex met Jordan, no update posted.",
    "Alex met Jordan again, still no update posted.",
    "Still unanswered.",
)


@pytest.fixture()
def issue_facts(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """What GitHub says about each issue, editable by a case, never fetched."""
    facts: dict[str, str] = {"47": "OPEN|4|2/5"}
    monkeypatch.setattr(message_teammate, "_issue_facts", lambda number: facts[number])
    return facts


@pytest.fixture()
def sent(monkeypatch: pytest.MonkeyPatch, tmp_path, issue_facts) -> list[str]:
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
    # The sender read its worklist through the door before writing, so every
    # issue number on it is backed (the evidence check has its own test).
    monkeypatch.setattr(
        message_teammate._outbound,
        "door_readings",
        lambda window_seconds: [
            {"outcome": "ok", "excerpt": item["title"]}
            for item in state.worklist.open_items()
        ],
    )
    return calls


def _ask_then_note(item_id: int, ask: str, note: str) -> str:
    """One morning: the brief asks, then records its own note, both as the owner."""
    answer = message_teammate.execute({"person": "Alex", "message": ask}, actor="Alex")
    manage_worklist.execute(
        {"action": "progress", "item_id": item_id, "text": note}, owner="Alex"
    )
    return answer


def test_five_mornings_of_rewording_send_one_ask(sent: list[str]) -> None:
    """Five mornings of rewording with nothing else changed send one ask."""
    item_id = state.worklist.add_item("question", _CONTRACT_TITLE, owner="Alex")
    answers = [
        _ask_then_note(item_id, ask, note) for ask, note in zip(_ASKS, _PROGRESS_NOTES)
    ]
    assert not answers[0].startswith("not sent:"), answers[0]
    refused = [answer for answer in answers[1:] if answer.startswith("not sent:")]
    assert len(refused) == 4, answers
    assert len(sent) == 1, sent


def test_an_answer_on_the_issue_makes_the_ask_new(
    sent: list[str], issue_facts: dict[str, str]
) -> None:
    """The way back: a person commenting on the issue is a fact the assistant cannot fake."""
    item_id = state.worklist.add_item("question", _CONTRACT_TITLE, owner="Alex")
    _ask_then_note(item_id, _ASKS[0], _PROGRESS_NOTES[0])
    issue_facts["47"] = "OPEN|5|2/5"
    answer = _ask_then_note(item_id, _ASKS[1], _PROGRESS_NOTES[1])
    assert not answer.startswith("not sent:"), answer
    assert len(sent) == 2
