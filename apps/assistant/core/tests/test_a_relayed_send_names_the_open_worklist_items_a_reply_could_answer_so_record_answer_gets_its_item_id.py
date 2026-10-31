"""A relayed send names the open worklist items a reply could answer, so record_answer gets its item id.

WHAT IT PINS. `core.sent_feed.sends_after`, the read behind `GET /relay/sent`,
over a temporary state DB holding one page to the owner and worklist items owned by
The owner, by the assistant and by a teammate; and `openclaw_watch.chat_relay.note`, which turns
one send of that feed into the text the gateway's chat session reads.

WHY IT EXISTS. A reply closes a question only through `record_answer`, which
needs the worklist item's id. When nothing the chat sees carries one, it is
never called: the owner's "done" to a page about an item leaves the item open,
and the next brief reads it as unchanged.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Fixed by who
owns what: the owner's item and the assistant's own are ones the owner's reply can answer, and
A teammate's is not. Seven items owned by the owner are more than a page should carry, and
the five shown are the five touched last, which are the last five added.
"""
from __future__ import annotations

from apps.assistant.shared.name import ASSISTANT_NAME

import pytest

from apps.assistant.watch import chat_relay
from apps.assistant.core import outbound, sent_feed, state

_ALEX = "+15550100001"
_SAM = "+15550100011"


@pytest.fixture()
def registry(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """the owner and a teammate in the registry and an empty state DB."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("SIGNAL_PEOPLE", f"{_ALEX}=Alex:founder:{_ALEX},{_SAM}=Sam:founder:{_SAM}")
    monkeypatch.setenv("SIGNAL_RECIPIENT", _ALEX)
    state.reset_for_tests()


def test_the_note_names_the_recipients_items_and_assistants_but_not_a_teammates(registry: None) -> None:
    """The page to the owner carries the owner's and the assistant's open item ids, and the note tells the chat to record."""
    alexs = state.worklist.add_item("question", "Rotate the Anthropic key", owner="Alex")
    assistants = state.worklist.add_item("question", "catering 47: the caterer's price per head", owner="assistant")
    sams = state.worklist.add_item("question", "Sam's invoice run", owner="Sam")
    outbound.remember_sent("", "The example-api-key rotation was never recorded.")

    send = sent_feed.sends_after(0).sends[0]
    ids = {item["id"] for item in send["open_items"]}
    assert {alexs, assistants} <= ids and sams not in ids, (
        f"the page to Alex carried items {ids}; it must carry Alex's {alexs} and "
        f"{ASSISTANT_NAME}'s {assistants}, never Sam's {sams}"
    )
    note = chat_relay.note(send)
    assert f"[{alexs}]" in note and f"[{assistants}]" in note, f"the note names no item id: {note!r}"
    assert "record_answer" in note, "the note never says how a reply closes the item"


def test_a_long_list_is_capped_at_the_items_touched_last(registry: None) -> None:
    """Seven open items for the owner show as the five most recently moved."""
    added = [state.worklist.add_item("watch", f"watch {number}", owner="Alex") for number in range(7)]
    outbound.remember_sent("", "The nightly backup did not run.")

    shown = [item["id"] for item in sent_feed.sends_after(0).sends[0]["open_items"]]
    assert sorted(shown) == sorted(added[-5:]), f"the page carried {shown}; it must carry the last five, {added[-5:]}"
