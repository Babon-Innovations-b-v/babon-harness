"""The relay hands each send to its recipient's own session.

WHAT IT PINS. `openclaw_watch.chat_relay.watch` with the default delivery
(`deliver`), the docker commands it runs replaced by a recorder at its `run`
seam and the container's feed by a stand-in holding one send to the owner and one to a teammate.

WHY IT EXISTS. Since the gateway keeps one session per Signal sender, a note relayed into the old shared `agent:main:main` lands where nobody
talks any more, and the reply misses its question. A
recipient who has not written since the scope changed has no session yet, and
`chat.inject` refuses that as "session not found"; holding the cursor on it
would stop the relay until that person wrote.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The key shape is
upstream's, read off the running gateway (OpenClaw 2026.9.1, 2026-10-23):
`agent:<agent>:<channel>:direct:<peer>` under "per-channel-peer", with the
Signal peer being the sender's E.164 number. The refusal text is the gateway's
`chat.inject` handler's own.
"""
from __future__ import annotations

from apps.assistant.shared.name import ASSISTANT_NAME

import subprocess
from collections.abc import Sequence

from apps.assistant.watch import chat_relay

_ALEX = "+15550100001"
_ROBIN = "+15550100017"
_SENDS = [
    {
        "id": 7, "sent_at": "2026-10-16T10:04:00+00:00", "loop": "teammate-asked",
        "road": "a message someone asked me to send", "recipient": "Alex", "address": _ALEX,
        "text": "Robin asks whether you can meet on Monday.",
    },
    {
        "id": 8, "sent_at": "2026-10-16T11:08:00+00:00", "loop": "page",
        "road": "an alert page", "recipient": "Robin", "address": _ROBIN,
        "text": "The marketing site build failed.",
    },
]


def _fetcher(after: int) -> tuple[int, list[dict]]:
    return 8, [send for send in _SENDS if send["id"] > after]


class _Gateway:
    """Records each docker command; `chat.inject` refuses the sessions named in `missing`."""

    def __init__(self, missing: frozenset[str] = frozenset()) -> None:
        self.calls: list[list[str]] = []
        self.missing = missing

    def __call__(self, argv: Sequence[str]) -> subprocess.CompletedProcess:
        self.calls.append(list(argv))
        if "chat.inject" in argv and any(key in argv[-1] for key in self.missing):
            return subprocess.CompletedProcess(list(argv), 1, "", "Error: session not found")
        return subprocess.CompletedProcess(list(argv), 0, "{}", "")


def _event_keys(calls: list[list[str]]) -> list[str]:
    return [call[call.index("--session-key") + 1] for call in calls if "--session-key" in call]


def test_each_note_goes_to_the_session_of_the_person_it_was_sent_to(tmp_path) -> None:
    """the owner's note reaches the owner's session and a teammate's reaches a teammate's, never the shared one."""
    gateway = _Gateway()
    assert chat_relay.watch(tmp_path, _fetcher, lambda key, text: chat_relay.deliver(key, text, gateway)) == 0
    keys = _event_keys(gateway.calls)
    assert keys == [f"agent:main:signal:direct:{_ALEX}", f"agent:main:signal:direct:{_ROBIN}"], (
        f"the relay queued notes for {keys}; each must go to its recipient's own session"
    )
    assert not any("agent:main:main" in " ".join(call) for call in gateway.calls), "a note went to the shared session"


def test_a_recipient_with_no_session_yet_does_not_stop_the_relay(tmp_path) -> None:
    """A refused inject for a session that does not exist yet still moves the cursor on."""
    gateway = _Gateway(missing=frozenset({_ROBIN}))
    assert chat_relay.watch(tmp_path, _fetcher, lambda key, text: chat_relay.deliver(key, text, gateway)) == 0
    assert (tmp_path / chat_relay.CURSOR_FILE).read_text().strip() == "8", (
        f"the relay stopped on a recipient who has not written to {ASSISTANT_NAME} since the scope changed"
    )
