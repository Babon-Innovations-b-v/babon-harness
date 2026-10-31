"""The chat relay injects each outside send once, naming recipient, time and road, and retries a failed inject.

WHAT IT PINS. `openclaw_watch.chat_relay.watch`, the pass the
`openclaw-chat-relay` timer runs, with the container's feed and the gateway's
`chat.inject` replaced by stand-ins at the two seams it takes (`fetcher`,
`injector`) and its cursor in a temporary state directory.

WHY IT EXISTS. The relay is how a reply in the gateway's chat session finds the
question the assistant asked from somewhere else. Three ways it can go wrong
quietly: a send injected twice shows the assistant its own message twice; a send skipped
after a failed inject is gone for good, because the cursor has moved past it;
and a note that does not say whose words these are, to whom and when, reads to
the model as text from nowhere.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The send was
stamped 06:00 UTC on Tuesday 6 October 2026, which is 08:00 in local under
summer time; the recipient and road are the feed's own fields. The pass
sequence is fixed by the contract: the gateway refuses the second inject once,
so pass one delivers only the first send and exits 0, pass two delivers the
second, and pass three delivers nothing.
"""
from __future__ import annotations

from apps.assistant.watch import chat_relay

_SENDS = [
    {
        "id": 3,
        "sent_at": "2026-10-06T06:00:00+00:00",
        "loop": "teammate-self",
        "road": "a message nobody asked for (the brief, the advisor or my own initiative)",
        "recipient": "Alex",
        "text": "Did Jordan give the caterer's price per head? Put the number on issue 47.",
    },
    {
        "id": 5,
        "sent_at": "2026-10-06T07:30:00+00:00",
        "loop": "page",
        "road": "an alert page",
        "recipient": "Alex",
        "text": "The nightly backup did not run.",
    },
]


def _fetcher(after: int) -> tuple[int, list[dict]]:
    """The container's feed: newest row 9 (rows 6 to 9 are not relayable), sends past `after`."""
    return 9, [send for send in _SENDS if send["id"] > after]


def test_each_send_is_injected_once_and_a_refused_one_is_retried(tmp_path) -> None:
    injected: list[str] = []
    refusals = {"left": 1}

    def injector(key: str, text: str) -> bool:
        if "nightly backup" in text and refusals["left"]:
            refusals["left"] -= 1
            return False
        injected.append(text)
        return True

    for _ in range(3):
        assert chat_relay.watch(tmp_path, _fetcher, injector) == 0, (
            "one failed pass must not page; only five in a row may"
        )
    assert [text.endswith(send["text"]) for text, send in zip(injected, _SENDS)] == [True, True], (
        f"the relay injected {injected!r}; it must inject the brief, then the "
        "refused page on the next pass, each once and in order"
    )
    assert len(injected) == 2, "a send was injected twice or a refused one was dropped"


def test_the_note_names_recipient_time_and_road() -> None:
    note = chat_relay.note(_SENDS[0])
    assert note.startswith("[Sent by me to Alex on Tue 6 Oct 08:00, from a message nobody asked for"), note
    assert "my own words" in note, "the note does not tell the model these were its own words"
