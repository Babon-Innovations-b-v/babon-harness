"""A page goes to the assistant's notify door; a deadman page and a page the
door will not take go straight to signal-cli, from the bot to the owner.

WHAT IT PINS. `alerts.notify.fan_out` and `send_signal`, against two real
loopback HTTP servers standing in for the assistant and for signal-cli's REST
API. What is checked is what those servers received.

WHERE THE EXPECTED ANSWERS COME FROM. The routing contract in notify's
docstring and the signal-cli REST shape (`POST /v2/send` with `number`,
`recipients`, `message`). A long body is split, never cut, because the thing
to do is usually its last line.
"""
from __future__ import annotations

import pytest

from infra.observability.alerts import notify

BOT = "+10000000001"
OWNER = "+10000000002"


@pytest.fixture
def roads(monkeypatch, fake_server):
    assistant = fake_server()
    signal_cli = fake_server()
    monkeypatch.setenv("ASSISTANT_URL", assistant.url)
    monkeypatch.setenv("SIGNAL_CLI_URL", signal_cli.url)
    monkeypatch.setenv("SIGNAL_BOT_NUMBER", BOT)
    monkeypatch.setenv("SIGNAL_ALLOWLIST", f"{OWNER},+10000000003")
    monkeypatch.setenv("OPENCLAW_WEBHOOK_SECRET", "s3cret")
    monkeypatch.setenv("NOTIFY_GATEWAY_RETRY_S", "0")
    return assistant, signal_cli


def test_an_ordinary_page_goes_to_the_assistant_with_its_facts(roads) -> None:
    assistant, signal_cli = roads
    result = notify.fan_out("Unit failed: harness-backup.service", "body", facts={"exit_code": 1})
    assert result == {"signal": True}
    posted = assistant.posts_to("/webhook/notify")
    assert len(posted) == 1 and posted[0]["auth"] == "Bearer s3cret"
    assert posted[0]["json"]["facts"] == {"exit_code": 1}
    assert signal_cli.requests == []


def test_a_deadman_page_never_touches_the_assistant(roads) -> None:
    assistant, signal_cli = roads
    assert notify.fan_out("Assistant is down", "detail", signal_direct=True) == {"signal": True}
    assert assistant.requests == []
    sent = signal_cli.posts_to("/v2/send")
    assert [r["json"] for r in sent] == [
        {"number": BOT, "recipients": [OWNER], "message": "Assistant is down\n\ndetail"}
    ]


def test_a_door_that_keeps_refusing_is_retried_then_the_page_goes_direct(roads, monkeypatch) -> None:
    assistant, signal_cli = roads
    assistant.statuses["/webhook/notify"] = 503
    monkeypatch.setenv("NOTIFY_GATEWAY_ATTEMPTS", "3")
    assert notify.fan_out("Disk almost full", "/ is 91% full")["signal"] is True
    assert len(assistant.posts_to("/webhook/notify")) == 3
    assert signal_cli.posts_to("/v2/send")[0]["json"]["message"].endswith("/ is 91% full")


def test_no_road_at_all_is_reported_not_raised(monkeypatch, fake_server) -> None:
    monkeypatch.setenv("SIGNAL_CLI_URL", fake_server({"/v2/send": 500}).url)
    monkeypatch.setenv("SIGNAL_BOT_NUMBER", BOT)
    monkeypatch.setenv("SIGNAL_RECIPIENT", OWNER)
    assert notify.fan_out("x", "y", signal_direct=True) == {"signal": False}


def test_a_long_body_is_split_and_its_last_line_arrives() -> None:
    body = "\n".join(f"line {index} " + "x" * 60 for index in range(100)) + "\nDO THIS LAST"
    pieces = notify.compose_signal_pieces("subject", body)
    assert len(pieces) > 1
    assert all(len(piece) <= notify.SIGNAL_PIECE_MAX_CHARS for piece in pieces)
    assert pieces[-1].endswith("DO THIS LAST")
    assert "".join(pieces).replace("\n", "") == f"subject\n\n{body}".replace("\n", "")
