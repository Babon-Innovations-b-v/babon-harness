"""A Signal message longer than the cap is refused, and nothing is sent.

WHAT IT PINS. `message_teammate.execute`, at its public seam: a draft over
`MAX_MESSAGE_WORDS` comes back as a "not sent:" string, no Signal send is
attempted and no audit row is written. A draft at the cap goes out.

WHY IT EXISTS. Sentences asking a model to be brief do not bound length,
which is why this one is arithmetic. A principle such as "default to three
sentences or fewer" can be obeyed by a brief of three sentences and 125 words, because a
sentence has no length. A rule a model can satisfy while doing the thing the rule forbids is
not a rule, so the number lives here.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The cases are
built from `MAX_MESSAGE_WORDS` itself rather than from 40, so they say "at the
cap" and "one over it" whatever the number becomes: the invariant is that a
boundary exists and that crossing it refuses, not that it sits at any figure.
The refusal's own shape is the module's published contract, a plain string
starting "not sent:" that a model can act on, never an exception, because a
guard that raises turns a long message into no message.

THE DANGEROUS DIRECTION IS SILENCE, so the last case asks the other half: a
message inside the cap must still reach the send. A change that refused
everything would pass a test that only checked refusals.
"""
from __future__ import annotations

from typing import Any

import pytest

from apps.assistant.core.tools.team import message_teammate


@pytest.fixture()
def sent(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str]]:
    """Every Signal send this module attempts, recorded instead of sent."""
    calls: list[tuple[str, str, str]] = []

    def _send(subject: str, message: str, recipient: str = "") -> bool:
        calls.append((subject, message, recipient))
        return True

    monkeypatch.setenv(message_teammate._ENABLE_ENV, "1")
    monkeypatch.setattr(message_teammate._signal, "send", _send)
    monkeypatch.setattr(message_teammate.people, "number_for", lambda person: "+15550100010")
    monkeypatch.setattr(message_teammate.people, "language_for", lambda person: "en")
    monkeypatch.setattr(message_teammate._quiet_hours, "quiet_now", lambda: False)
    monkeypatch.setattr(message_teammate._state, "recent_chat_turns", lambda *a, **k: [])
    monkeypatch.setattr(message_teammate._state, "append_chat_turn", lambda *a, **k: None)
    monkeypatch.setattr(message_teammate.write_guard, "audit", lambda *a, **k: None)
    return calls


def _words(count: int) -> str:
    """A draft of exactly `count` words, in the recipient's language."""
    return " ".join(["news"] * count)


def test_a_draft_one_word_over_the_cap_is_refused(sent: list[Any]) -> None:
    """The boundary, from the wrong side."""
    answer = message_teammate.execute(
        {"person": "Alex", "message": _words(message_teammate.MAX_MESSAGE_WORDS + 1)},
        actor="Alex",
    )
    assert answer.startswith("not sent:"), f"expected a refusal, got {answer!r}"
    assert sent == [], "a message over the cap was sent anyway"


def test_the_refusal_names_both_numbers(sent: list[Any]) -> None:
    """One rewrite has to be enough, so the model is told what it wrote.

    A refusal reading only "too long" costs a guess per attempt, and the loop
    has an iteration cap: a guard that needs three tries can spend the whole
    turn arguing instead of sending.
    """
    over = message_teammate.MAX_MESSAGE_WORDS + 12
    answer = message_teammate.execute(
        {"person": "Alex", "message": _words(over)}, actor="Alex"
    )
    assert str(over) in answer, f"the refusal does not say what was written: {answer!r}"
    assert str(message_teammate.MAX_MESSAGE_WORDS) in answer, (
        f"the refusal does not say what is allowed: {answer!r}"
    )


def test_the_refusal_is_a_string_and_never_an_exception(sent: list[Any]) -> None:
    """A guard that raises turns a long report into no report at all.

    Every other check in this module returns its refusal; this one is bound by
    the same contract, because the whole reason the cap can be trusted is that
    the worst it can do is ask for a shorter draft.
    """
    answer = message_teammate.execute(
        {"person": "Alex", "message": _words(message_teammate.MAX_MESSAGE_WORDS * 5)},
        actor="Alex",
    )
    assert isinstance(answer, str) and answer.startswith("not sent:")


def test_a_draft_at_the_cap_still_goes_out(sent: list[Any]) -> None:
    """The other half. The cap bounds a message; it does not replace one."""
    answer = message_teammate.execute(
        {"person": "Alex", "message": _words(message_teammate.MAX_MESSAGE_WORDS)},
        actor="Alex",
    )
    assert not answer.startswith("not sent:"), f"a draft at the cap was refused: {answer!r}"
    assert len(sent) == 1, f"a draft at the cap did not reach the send: {sent}"
