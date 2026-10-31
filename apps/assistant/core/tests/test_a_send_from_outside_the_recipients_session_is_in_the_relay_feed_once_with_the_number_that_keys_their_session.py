"""A send from outside the recipient's session is in the relay feed once, with the number that keys their session.

WHAT IT PINS. `core.sent_feed.sends_after`, the read behind `GET /relay/sent`,
over the `chat_turns` rows the send roads write: `outbound.remember_sent` for a
page, and `state.append_chat_turn` with the loop `message_teammate` records for
a send booked to the assistant (the brief) and for one a person asked for in a chat.

WHY IT EXISTS. The brief runs in an isolated cron session, so a "Yes" to a
question the brief asked can be read as an answer to something else. The VM
relay copies this feed into the recipient's own session. Since
each person has their own session, a message a teammate asked the assistant to
send another leaves from the asker's session, so the recipient's session never
saw it and it has to be relayed too. The relay keys the session by the number the send went to.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Fixed by what
was sent, not by the feed: the brief's question, the night page and the message
A teammate's request produced all went to the owner from outside the owner's session, so all
three come back, oldest first, naming the owner and their number; and past the last id
returned nothing comes back again.
"""
from __future__ import annotations

import pytest

from apps.assistant.core import outbound, sent_feed, state

_ALEX = "+15550100001"
_BRIEF = "Did Jordan give the caterer's price per head yesterday? Put the number on issue 47."
_PAGE = "The nightly backup did not run; the disk is at 93%."
_ASKED = "Sam asked me to tell you the Monday briefing moves to 10:00."


@pytest.fixture()
def sent(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """the owner in the registry, and three sends written the way their roads write them."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("SIGNAL_PEOPLE", f"{_ALEX}=Alex:founder:{_ALEX}")
    monkeypatch.setenv("SIGNAL_RECIPIENT", _ALEX)
    state.reset_for_tests()
    state.append_chat_turn(_ALEX, "assistant", _BRIEF, loop="teammate-self")
    outbound.remember_sent("", _PAGE)
    state.append_chat_turn(_ALEX, "assistant", _ASKED, loop="teammate-asked")
    state.append_chat_turn(_ALEX, "user", "Yes")


def test_every_send_from_outside_the_recipients_session_is_in_the_feed_with_their_number(
    sent: None,
) -> None:
    """The brief, the page and the asked-for message come back in order, named, with the owner's number."""
    feed = sent_feed.sends_after(0)
    texts = [send["text"] for send in feed.sends]
    assert texts == [_BRIEF, _PAGE, _ASKED], (
        f"the relay feed held {texts!r}; it must hold the brief, the page and the "
        "message Sam asked for, in that order"
    )
    assert {send["recipient"] for send in feed.sends} == {"Alex"}, "a send is not named by its recipient"
    assert {send["address"] for send in feed.sends} == {_ALEX}, "a send does not carry the number its session is keyed by"


def test_nothing_comes_back_past_the_last_send_returned(sent: None) -> None:
    """A relay that advanced its cursor to the last id never sees that send again."""
    first = sent_feed.sends_after(0)
    again = sent_feed.sends_after(int(first.sends[-1]["id"]))
    assert again.sends == [], "a send already relayed came back, so it would be injected twice"
    assert again.newest_id >= first.sends[-1]["id"]
