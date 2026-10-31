"""`my_actions` shows a message the assistant sent from outside the chat, in its own words, once.

WHAT IT PINS. `my_actions.execute`, the door read tool, over the two tables
every send path writes: `chat_turns` (an `assistant` row after each delivered
Signal message, from `message_teammate`, the meeting reminder and
`core.outbound.remember_sent`) and `assistant_actions` (a `team_message` row for a
`message_teammate` send only).

WHY IT EXISTS. The gateway answers every inbound message in one chat session,
and the weekday brief runs in an isolated cron session, so that session never
saw the question a reply answers. Say the brief asks the owner whether
Jordan has sent the caterer's price per head, and the owner answers "Yes": the
chat session cannot tell which question that answers.
`my_actions` read `assistant_actions` only, so a send that left without a
`team_message` row was invisible there too.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The texts are
two sends three days apart, in the shape the container writes them. What must come back is fixed
by the sequence, not by the formatter: the later question, in its own
words and addressed to the owner by name, and the earlier catering message exactly
once, although it sits in both tables.
"""
from __future__ import annotations

from apps.assistant.shared.name import ASSISTANT_NAME

import pytest

from apps.assistant.core import state
from apps.assistant.core.tools.meta import my_actions

_ALEX = "+15550100001"

_BRIEF_QUESTION = (
    "Nothing broke overnight, calendar clear. One thing: did Jordan send the caterer's "
    "price per head yesterday? It has to be EUR 24.50 or less. Put "
    "the number on issue 47."
)
_CONTRACT_ASK = (
    "Thursday 14:00 with the caterer: ask Jordan what the price per head is for the "
    "team day lunch, and whether we can book all 40 places. Under 30 places "
    "the group rate lapses (#47)."
)


@pytest.fixture()
def sent(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """the owner in the registry, and two sends the way the container records them."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("SIGNAL_PEOPLE", f"{_ALEX}=Alex:founder:{_ALEX}")
    state.reset_for_tests()
    # message_teammate: the audit row, then the chat turn.
    state.record_action("team_message", "signal Alex", _CONTRACT_ASK[:80], actor="Alex", detail=_CONTRACT_ASK)
    state.append_chat_turn(_ALEX, "assistant", _CONTRACT_ASK)
    # A send that wrote only the chat turn, the way remember_sent does.
    state.append_chat_turn(_ALEX, "assistant", _BRIEF_QUESTION)
    # What the owner said is not something the assistant sent.
    state.append_chat_turn(_ALEX, "user", "Yes")


def test_a_question_sent_from_outside_the_chat_is_shown_in_its_own_words(sent: None) -> None:
    answer = my_actions.execute({})
    assert _BRIEF_QUESTION in answer, (
        "the brief's question is not in my_actions, so the chat session still "
        "cannot see what Alex's 'Yes' answers"
    )
    assert "-> Alex:" in answer, "the send is not addressed to Alex by name"
    assert "Yes" not in answer.replace(_BRIEF_QUESTION, ""), (
        f"an inbound message was listed as something {ASSISTANT_NAME} sent"
    )


def test_a_teammate_message_in_both_tables_is_shown_once(sent: None) -> None:
    answer = my_actions.execute({"about": "alex"})
    assert answer.count("team day lunch") == 1, (
        "a message_teammate send is listed twice, once per table"
    )
