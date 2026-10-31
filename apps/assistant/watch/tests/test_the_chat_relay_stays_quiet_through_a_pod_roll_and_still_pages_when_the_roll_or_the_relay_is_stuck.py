"""The chat relay stays quiet through a container restart and still pages when the roll or the relay is stuck.

WHAT IT PINS. `openclaw_watch.chat_relay.watch`, the pass the
`harness-assistant-chat-relay` timer runs, driven through its `fetcher` and `injector`
seams; and `fetch`, which sorts the container's answer, driven through `urlopen`,
the one network call it makes.

WHY IT EXISTS. A deploy can put the new relay unit in place minutes before
the new pod is up. Meanwhile the old pod answers 404 for the feed and the
rolling one 502, and with a plain five-failures limit the relay exits non-zero
and pages someone for a roll that is going fine.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The timer
beats every two minutes. A pod not serving the feed may fail for thirty
minutes before a page, so passes 1 to 14 exit 0 and pass 15 exits 1. Any other
failure, here an inject the gateway refuses, keeps the ten-minute limit, so
passes 1 to 4 exit 0 and pass 5 exits 1. The statuses are what a roll looks
like behind Caddy: 404 from the old pod, 502 while no pod answers; 401 (a
wrong secret) and 500 (a crash in the route) are faults, not a roll.
"""
from __future__ import annotations

from email.message import Message
from urllib.error import HTTPError

import pytest

from apps.assistant.watch import chat_relay


def _old_pod(after: int) -> tuple[int, list[dict]]:
    """The old pod of a roll: the feed route is not there yet."""
    raise chat_relay.PodNotServing(f"{chat_relay.ROUTE} answered HTTP 404")


def _one_send(after: int) -> tuple[int, list[dict]]:
    """A feed holding one page not yet relayed."""
    send = {
        "id": 1,
        "sent_at": "2026-10-07T16:00:00+00:00",
        "loop": "page",
        "road": "an alert page",
        "recipient": "Alex",
        "text": "The nightly backup did not run.",
    }
    return 1, [send] if after < 1 else []


def test_a_pod_roll_pages_only_after_thirty_minutes(tmp_path) -> None:
    exits = [chat_relay.watch(tmp_path, _old_pod, lambda key, text: True) for _ in range(15)]
    assert exits == [0] * 14 + [1], (
        f"exit codes {exits}: a pod not serving the feed must page on pass 15 (30 min), not before"
    )


def test_a_refused_inject_still_pages_after_ten_minutes(tmp_path) -> None:
    exits = [chat_relay.watch(tmp_path, _one_send, lambda key, text: False) for _ in range(5)]
    assert exits == [0, 0, 0, 0, 1], f"exit codes {exits}: a stuck relay must page on pass 5 (10 min)"


@pytest.mark.parametrize(("status", "rolling"), [(404, True), (502, True), (401, False), (500, False)])
def test_fetch_tells_a_roll_from_a_fault(monkeypatch, status: int, rolling: bool) -> None:
    def refuse(*args, **kwargs):
        raise HTTPError(chat_relay.BASE_URL, status, "refused", Message(), None)

    monkeypatch.setattr(chat_relay.urllib.request, "urlopen", refuse)
    with pytest.raises(RuntimeError) as raised:
        chat_relay.fetch("secret", 0)
    assert isinstance(raised.value, chat_relay.PodNotServing) is rolling, (
        f"HTTP {status} was sorted as {'a fault' if rolling else 'a roll'}"
    )
