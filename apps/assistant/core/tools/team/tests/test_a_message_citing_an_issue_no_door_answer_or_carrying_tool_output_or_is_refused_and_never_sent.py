"""A message citing an issue no door answer held, or carrying tool output or narration, is refused and never sent.

WHAT IT PINS. `message_teammate`, reached the way the gateway reaches it: over
the MCP door (`gates/mcp.py`), with a read made through the same door first.
The door keeps every OK answer it hands out (`outbound.remember_door_reading`),
and the send refuses a message that cites an issue number none of those
answers of the last half hour held, or that is the assistant's working rather than a
message: a pasted tool answer or "let me check ..." narration.

WHY IT EXISTS. Three shapes reach a person that are not messages: a list of
issue numbers and titles no tool returned, opening "Let me check the current
state of this service"; a status tool's answer pasted whole ("change_feed:
..."); and "Let me re-read what the tool returned before stating
that as fact." The send the gateway uses has to check for all
three itself.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. By reading the
door's answer as a person would: the `gh_issue_list` answer below lists issues
47 and 151 and nothing else, so a message about #38 cites an issue nobody
read and one about #47 cites one that was read. The narration and the dump
below are synthetic examples of the assistant's working, and a message to a person
opening "Let me check" or carrying "change_feed:" is not a message on its face.
"""
from __future__ import annotations

from apps.assistant.shared.name import ASSISTANT_NAME

import json

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from apps.assistant.core import state, tools
from apps.assistant.core.tools.team import message_teammate
from apps.assistant.gates import mcp

_BEARER = "door-test-bearer"
_PEOPLE = "uuid:alex-uuid=Alex:dev:+15550100001"

# The shape `gh_issue_list` answers in: number, state, title, labels, date.
_BOARD = (
    "47\tOPEN\tSupplier contract\tPRD, area:finance\t2026-09-28T10:00:00Z\n"
    "151\tOPEN\tDev backlog\tPRD, area:dev\t2026-07-10T09:00:00Z"
)

# Synthetic examples of the assistant narrating its work or dumping tool output.
_NARRATION_FIRST = (
    "Let me check the current state of this service and any open issues "
    "first."
)
_TOOL_DUMP = (
    "deploy: last confirmed deploy 0a0a0a0a at 10:00; components: nothing down; "
    "change_feed: 'morning' last marked at 06:00"
)
_NARRATION_SECOND = (
    "Let me re-read what the tool returned before stating that "
    "as fact."
)


@pytest.fixture()
def door(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """A live door over a real state database, with every Signal send recorded."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("OPENCLAW_WEBHOOK_SECRET", _BEARER)
    monkeypatch.setenv("SIGNAL_PEOPLE", _PEOPLE)
    monkeypatch.setenv(message_teammate._ENABLE_ENV, "1")
    state.reset_for_tests()
    sent: list[str] = []

    def _send(subject: str, message: str, recipient: str = "") -> bool:
        sent.append(message)
        return True

    def _execute(name: str, arguments: dict) -> tools.result.ToolResult:
        return tools.result.ok(name, _BOARD)

    monkeypatch.setattr(message_teammate._signal, "send", _send)
    monkeypatch.setattr(message_teammate._quiet_hours, "quiet_now", lambda: False)
    monkeypatch.setattr(message_teammate, "_issue_facts", lambda number: "OPEN|0|0/0")
    monkeypatch.setattr(mcp.tools, "execute_typed", _execute)
    built = mcp.assistant_mcp_door()
    app = Starlette(
        routes=[Route("/mcp", built.asgi_app, methods=["POST"])],
        lifespan=built.lifespan,
    )
    with TestClient(app) as client:
        yield client, sent


def _call(client: TestClient, tool: str, arguments: dict) -> str:
    """One `tools/call` over the door, answered as its text."""
    response = client.post(
        "/mcp",
        headers={
            "authorization": f"Bearer {_BEARER}",
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
        },
        content=json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": tool, "arguments": arguments},
            }
        ),
    )
    assert response.status_code == 200, response.text
    return response.json()["result"]["content"][0]["text"]


def _tell_alex(client: TestClient, message: str) -> str:
    return _call(
        client,
        "message_teammate",
        {"person": "Alex", "message": message, "requested_by": "Alex"},
    )


def test_an_issue_no_door_answer_held_is_refused(door) -> None:
    """an issue was never read; an issue was. Only the second goes out."""
    client, sent = door
    _call(client, "gh_issue_list", {"state": "open"})
    invented = _tell_alex(client, "#38 webhook is failing.")
    assert "not sent:" in invented and "#38" in invented, invented
    assert sent == [], "an issue no tool returned reached the phone"
    real = _tell_alex(client, "#47 is still open: the supplier contract waits on you.")
    assert "messaged Alex" in real, real
    assert len(sent) == 1


def test_tool_output_and_narration_are_refused(door) -> None:
    """The three examples are the assistant's working, so none of them is sent."""
    client, sent = door
    _call(client, "gh_issue_list", {"state": "open"})
    for draft in (_NARRATION_FIRST, _TOOL_DUMP, _NARRATION_SECOND):
        answer = _tell_alex(client, draft)
        assert "not sent:" in answer, (draft, answer)
    assert sent == [], f"{ASSISTANT_NAME}'s working reached the phone"


def test_a_message_without_numbers_or_working_still_goes(door) -> None:
    """The ordinary relay is untouched, with no read behind it at all."""
    client, sent = door
    answer = _tell_alex(client, "Sam asked me to say the 10:00 call is on. Let me know if that clashes.")
    assert "messaged Alex" in answer, answer
    assert len(sent) == 1
