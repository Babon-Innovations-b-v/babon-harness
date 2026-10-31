"""Every relayed send is queued as a system event the model reads, because chat.inject alone is transcript-only.

WHAT IT PINS. `openclaw_watch.chat_relay.deliver`, the default way a relay pass
hands a send to the gateway, with the docker commands it runs replaced by a
recorder at its `run` seam, driven through `watch` with a stand-in feed.

WHY IT EXISTS. Upstream OpenClaw marks what `chat.inject` writes as
transcript-only and never replays it to the model. A relay that only injects
copies every page into the chat and the model never reads one, so a reply to
the newest page is answered against whatever older thread the model last
saw. The
note has to reach the model through the session's system-event queue, which
the gateway drains into the next inbound turn.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The command
shape is upstream's CLI as read from the live gateway (OpenClaw 2026.9.1,
`openclaw system event --help`): `--session-key`, `--mode next-heartbeat`,
`--text`. The note text is the relay's own `note()` of the send, which the
sibling relay test pins.
"""
from __future__ import annotations

import subprocess
from collections.abc import Sequence

from apps.assistant.watch import chat_relay

_SEND = {
    "id": 4,
    "sent_at": "2026-10-14T16:04:00+00:00",
    "loop": "page",
    "road": "an alert page",
    "recipient": "Alex",
    "text": "Repo index stale: the graph index has not been rebuilt since Monday.",
}


def _fetcher(after: int) -> tuple[int, list[dict]]:
    """The container's feed: one page past `after`."""
    return 4, [_SEND] if after < 4 else []


class _Gateway:
    """Records each docker command and answers it, refusing the system event when told to."""

    def __init__(self, refuse_event: bool = False) -> None:
        self.calls: list[list[str]] = []
        self.refuse_event = refuse_event

    def __call__(self, argv: Sequence[str]) -> subprocess.CompletedProcess:
        self.calls.append(list(argv))
        refused = self.refuse_event and "system" in argv
        return subprocess.CompletedProcess(list(argv), 1 if refused else 0, "", "")


def _events(calls: list[list[str]]) -> list[list[str]]:
    return [call for call in calls if call[4:6] == ["system", "event"]]


def test_each_send_is_queued_for_the_model_and_injected_into_the_transcript(tmp_path) -> None:
    """One pass queues the note on the chat session and also injects it."""
    gateway = _Gateway()
    assert chat_relay.watch(tmp_path, _fetcher, lambda key, text: chat_relay.deliver(key, text, gateway)) == 0
    events = _events(gateway.calls)
    assert len(events) == 1, f"the relay ran {gateway.calls!r}; it must queue the page as a system event once"
    event = events[0]
    assert event[event.index("--session-key") + 1] == chat_relay.session_key(_SEND)
    assert event[event.index("--mode") + 1] == "next-heartbeat", "any other mode starts a model run"
    assert event[event.index("--text") + 1] == chat_relay.note(_SEND)
    assert any("chat.inject" in call for call in gateway.calls), "the transcript copy was dropped"


def test_a_refused_system_event_holds_the_cursor_so_the_send_is_retried(tmp_path) -> None:
    """A note the model could not be handed is not counted as relayed."""
    gateway = _Gateway(refuse_event=True)
    assert chat_relay.watch(tmp_path, _fetcher, lambda key, text: chat_relay.deliver(key, text, gateway)) == 0
    cursor = (tmp_path / chat_relay.CURSOR_FILE).read_text().strip() if (tmp_path / chat_relay.CURSOR_FILE).exists() else "0"
    assert cursor == "0", f"the cursor moved to {cursor} past a send the model never got"
