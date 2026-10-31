"""The gateway fragment gives each Signal sender their own session.

WHAT IT PINS. `workspace/gateway_config_patch.json`, the fragment step 68
applies with `openclaw config patch --stdin`, and its `session.dmScope`.

WHY IT EXISTS. With no scope set, upstream's default "main" puts every
allowlisted Signal DM in one session, `agent:main:main`. A teammate's
"can we meet on Monday?" and the owner's own messages then run in that one session,
so each person's private chat turns sit in the context of everyone else's. This isolates chat history between people; it does not limit
what a tool such as `agenda_view` can read for them.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Read off the
running gateway (OpenClaw 2026.9.1, 2026-10-23): `buildAgentPeerSessionKey`
gives "per-channel-peer" the key `agent:main:signal:direct:<peer>`, and the
Signal plugin's peer for a sender with a number is that E.164 number. That is
the key the chat relay builds, so the two must agree on this scope.
"""
from __future__ import annotations

from apps.assistant.workspace import fragment




def test_the_gateway_fragment_gives_each_signal_sender_their_own_session() -> None:
    """Each sender is keyed by channel and peer, the shape the chat relay writes into."""
    patch = fragment.render_config_patch()
    assert patch.get("session", {}).get("dmScope") == "per-channel-peer", (
        "the gateway fragment leaves every Signal DM in one shared session"
    )
