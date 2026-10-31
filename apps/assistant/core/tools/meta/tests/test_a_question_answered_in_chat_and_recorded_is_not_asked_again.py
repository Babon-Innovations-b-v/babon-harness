"""A question answered in chat and recorded is not asked again.

WHAT IT PINS. `record_answer` (served over the MCP door) with
`message_teammate`, at their public seams: once the chat session records a
teammate's answer to an open worklist item, a later `message_teammate` naming
that item to the same person is refused and never sent, even after the issue
moved; the answer is on the worklist block the brief reads; telling somebody
else is still allowed; and the tool refuses an unknown or closed item, an
answerer the registry does not hold and an empty answer, writing nothing.

WHY IT EXISTS. The assistant asks in a cron session and hears the reply in the
gateway's chat session, which reaches nothing of ours without this. An
answer that stays in a transcript lets the next brief ask the same question
again.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From what a
person would see, replaying the sequence: the brief asks the owner once
(sent), the owner answers "EUR 24.50" in chat, the session records it, a comment
lands on the issue, and next morning's same ask must not reach their phone. A teammate,
never asked, may still be told.
"""
from __future__ import annotations

import pytest

from apps.assistant.core import state
from apps.assistant.core.tools import gateway_surface, write_tools
from apps.assistant.core.tools.meta import manage_worklist
from apps.assistant.core.tools.team import message_teammate
from apps.assistant.workspace import capabilities

_CONTRACT_TITLE = "Issue 47 catering: the caterer's price per head for the team day"
_ASK = "catering 47: what is the caterer's price per head? Jordan needs it."
_PEOPLE = "uuid:a=Alex:dev:+15550100012,uuid:b=Sam:dev:+15550100013"


@pytest.fixture()
def world(monkeypatch: pytest.MonkeyPatch, tmp_path) -> dict:
    """A real state database, a two-person registry, sends recorded not sent."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("SIGNAL_PEOPLE", _PEOPLE)
    monkeypatch.delenv(gateway_surface.DOOR_WRITE_ENV, raising=False)
    state.reset_for_tests()
    sent: list[tuple[str, str]] = []
    issue = {"facts": "OPEN|4|2/5"}

    def _send(subject: str, message: str, recipient: str = "") -> bool:
        sent.append((recipient, message))
        return True

    monkeypatch.setenv(message_teammate._ENABLE_ENV, "1")
    monkeypatch.setattr(message_teammate._signal, "send", _send)
    monkeypatch.setattr(message_teammate.people, "language_for", lambda p: "en")
    monkeypatch.setattr(message_teammate._quiet_hours, "quiet_now", lambda: False)
    monkeypatch.setattr(message_teammate._state, "recent_chat_turns", lambda *a, **k: [])
    monkeypatch.setattr(message_teammate.write_guard, "audit", lambda *a, **k: None)
    monkeypatch.setattr(message_teammate, "_unread_evidence_refusal", lambda *a: None)
    monkeypatch.setattr(message_teammate, "_issue_facts", lambda number: issue["facts"])
    added = manage_worklist.execute(
        {"action": "add", "kind": "question", "title": _CONTRACT_TITLE}, owner="assistant"
    )
    item_id = int(added.split("item ")[1].split(" ")[0])
    return {"sent": sent, "issue": issue, "item_id": item_id}


def _ask(person: str) -> str:
    return message_teammate.execute({"person": person, "message": _ASK}, actor="assistant")


def _record(item_id, answer: str, answered_by: str) -> str:
    return write_tools.dispatch(
        write_tools.RECORD_ANSWER,
        {"item_id": item_id, "answer": answer, "answered_by": answered_by},
        write_tools.Actor(name="Alex", loop="chat"),
    )


def test_the_catering_sequence_is_not_asked_again_after_alex_answers(world: dict) -> None:
    """Ask, the owner answers in chat and it is recorded, next morning refused."""
    first = _ask("Alex")
    assert not first.startswith("not sent:"), first
    recorded = _record(world["item_id"], "EUR 24.50", "alex")
    assert write_tools.was_success(write_tools.RECORD_ANSWER, recorded), recorded
    world["issue"]["facts"] = "OPEN|5|2/5"  # a comment landed overnight
    again = _ask("Alex")
    assert again.startswith("not sent:"), again
    assert "EUR 24.50" in again
    assert len(world["sent"]) == 1, world["sent"]


def test_the_brief_still_sees_and_can_pass_on_the_answer(world: dict) -> None:
    """The answer is on the worklist block, and another reader may be told."""
    _ask("Alex")
    _record(world["item_id"], "EUR 24.50", "Alex")
    block = state.worklist.render()
    assert "EUR 24.50" in block and "Alex" in block
    told_sam = _ask("Sam")
    assert not told_sam.startswith("not sent:"), told_sam


@pytest.mark.parametrize(
    ("item", "answer", "answered_by"),
    [
        (9999, "EUR 24.50", "Alex"),
        ("not-a-number", "EUR 24.50", "Alex"),
        (None, "   ", "Alex"),
        (None, "EUR 24.50", "Jordan"),
    ],
)
def test_a_refused_answer_writes_nothing(world: dict, item, answer, answered_by) -> None:
    """Unknown item, bad id, empty answer, a stranger: refused, nothing kept."""
    result = _record(world["item_id"] if item is None else item, answer, answered_by)
    assert result.startswith("refused:"), result
    assert state.worklist.item(world["item_id"])["answer"] is None
    assert not state.reported_items.answered_keys(
        [f"worklist:{world['item_id']}@alex", f"worklist:{world['item_id']}@jordan"]
    )


def test_a_closed_item_is_refused(world: dict) -> None:
    """A closed item is not waiting on anybody."""
    state.worklist.close_item(world["item_id"], "settled on the issue")
    result = _record(world["item_id"], "EUR 24.50", "Alex")
    assert result.startswith("refused:"), result


def test_the_door_serves_it_and_tells_the_chat_session(world: dict) -> None:
    """Served with `requested_by` required, and named in the capability block."""
    served = {d["name"]: d for d in gateway_surface.write_definitions()}
    schema = served[write_tools.RECORD_ANSWER]["input_schema"]
    assert gateway_surface.REQUESTER_ARGUMENT in schema["required"]
    assert write_tools.RECORD_ANSWER in capabilities.render_capabilities()
