"""A worklist item the reader has been told, and that has not moved, is refused.

WHAT IT PINS. `message_teammate.execute`, at its public seam: a message naming
an issue number that belongs to an OPEN worklist item this person owns is sent
once, recorded in `reported_items`, and refused the second time while the item's
material state is unchanged. The issue moving (a comment) makes it sayable again.

WHY IT EXISTS. `state/reported_items.py` was written for exactly this. Without
a caller nothing counts a repeat, and one item can reach a person on
consecutive mornings in the same words.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From the
ledger's own published rule rather than from this caller: "same fingerprint as
yesterday means nothing about the item changed, so it may not be narrated
again", where the fingerprint is the item's status plus the facts of its issue. So the first telling goes, the second with nothing moved does not, and
a telling after the issue gains a comment goes again. Each case asserts what a person would observe, a
message sent or a refusal, never an internal.

THE DANGEROUS DIRECTION IS SILENCE, so three of the five cases ask the other
half: a first telling goes, a moved item goes again, and an item belonging to
somebody else is not this reader's repeat. A guard that refused everything
would pass a test that only counted refusals.
"""
from __future__ import annotations

import pytest

from apps.assistant.core import state
from apps.assistant.core.tools.team import message_teammate


@pytest.fixture()
def issue_facts(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """What GitHub says about each issue, editable by a case, never fetched."""
    facts: dict[str, str] = {}
    monkeypatch.setattr(
        message_teammate, "_issue_facts", lambda number: facts.get(number, "OPEN|0|0/0")
    )
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


def _tell(message: str, person: str = "Alex") -> str:
    return message_teammate.execute({"person": person, "message": message}, actor=person)


def test_the_first_telling_goes_out(sent: list[str]) -> None:
    """Nothing is known yet, so there is nothing to repeat."""
    state.worklist.add_item("watch", "Issue 12: backup job failed", owner="Alex")
    answer = _tell("Issue 12 still needs your journalctl read.")
    assert not answer.startswith("not sent:"), answer
    assert len(sent) == 1


def test_the_second_telling_of_an_unmoved_item_is_refused(sent: list[str]) -> None:
    """The same sentence about an unmoved item is not sent twice."""
    state.worklist.add_item("watch", "Issue 12: backup job failed", owner="Alex")
    _tell("Issue 12 still needs your journalctl read.")
    answer = _tell("#12 still needs your journalctl read.")
    assert answer.startswith("not sent:"), answer
    assert len(sent) == 1, "the repeat went out anyway"


def test_an_item_that_moved_is_sayable_again(
    sent: list[str], issue_facts: dict[str, str]
) -> None:
    """The ledger records material state, not the sentence the assistant wrote."""
    state.worklist.add_item("watch", "Issue 12: backup job failed", owner="Alex")
    _tell("Issue 12 still needs your journalctl read.")
    issue_facts["12"] = "OPEN|1|0/0"
    answer = _tell("#12 ran clean this morning.")
    assert not answer.startswith("not sent:"), answer
    assert len(sent) == 2


def test_somebody_elses_item_is_not_this_readers_repeat(sent: list[str]) -> None:
    """The ledger is keyed by item, not by reader, so the owner decides.

    Without this, telling the owner about a teammate's item would silence the telling
    that goes to a teammate, whose item it actually is.
    """
    state.worklist.add_item("watch", "Issue 27: backup restore test", owner="Robin")
    _tell("#27 is waiting on you.", person="Robin")
    answer = _tell("#27 is still open on Robin's side.", person="Alex")
    assert not answer.startswith("not sent:"), answer
    assert len(sent) == 2


def test_a_patrol_restamping_its_finding_is_not_a_change(sent: list[str]) -> None:
    """The way this guard would have been dead on arrival.

    Patrol opens every finding with the moment it looked, because the doctrine
    asks for a zone on a reported time, and it runs three times a day. Both
    strings below are real shapes off the container, one word apart in meaning and
    two hours apart in stamp. If the stamp counts as movement, the item reads
    as fresh three times a day and nothing is ever a repeat.
    """
    item_id = state.worklist.add_item(
        "watch", "Issue 27: backup restore test", owner="Alex"
    )
    state.worklist.record_progress(
        item_id,
        "2026-09-16 11:00 local time (CEST): Issue 27 still open, "
        "0 comments. Assigned to Robin, no activity. Unchanged.",
    )
    _tell("#27 is still waiting on Robin.")
    state.worklist.record_progress(
        item_id,
        "2026-09-16 13:00 local time (CEST): Issue 27 still open, "
        "0 comments. Assigned to Robin, no activity. Unchanged.",
    )
    answer = _tell("#27 is still waiting on Robin.")
    assert answer.startswith("not sent:"), (
        "a re-stamped finding read as movement, so the ledger calls every "
        f"patrol pass fresh news: {answer}"
    )
    assert len(sent) == 1


def test_a_message_naming_no_item_is_never_refused(sent: list[str]) -> None:
    """The guard reads issue numbers; ordinary messages must pass untouched."""
    state.worklist.add_item("watch", "Issue 12: backup job failed", owner="Alex")
    _tell("Issue 12 still needs your journalctl read.")
    answer = _tell("Booked Thursday 16:00 with Sam.")
    assert not answer.startswith("not sent:"), answer
    assert len(sent) == 2
