"""A write nobody asked for is booked to the assistant, and naming the assistant reaches only the tools it may use alone.

WHAT IT PINS. The MCP door (`gates/mcp.py`), called over HTTP the way the
gateway calls it, with `requested_by: "the assistant"`. A worklist item the assistant opens on
its own is recorded as the assistant's: the item's owner and the door's audit row both
say "assistant". A message the assistant sends on its own at night is held by quiet hours,
because the self-actor's holds come with the name. A GitHub board write under
that name reaches `github_act`, because the assistant has full board write
access. A bible edit under that name is still refused
before dispatch: `create_video_call` stays person-only.

WHY IT EXISTS. A model that tries `requested_by: "assistant"` and is told the
registry holds nobody by that name reasons "the owner didn't ask here" and
books the item to the owner. The door had no honest answer to "nobody
asked".

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From the rules
as written: nobody asked, so the record names the assistant; quiet hours are defined as
holding the assistant's own initiative; the owner's decision opens the board to the assistant; the
bible is not among the tools the assistant may use alone.
"""
from __future__ import annotations

from apps.assistant.shared.name import ASSISTANT_NAME

import json

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from apps.assistant.core import state
from apps.assistant.core.tools.team import message_teammate
from apps.assistant.gates import mcp

_BEARER = "door-test-bearer"
_PEOPLE = "uuid:alex-uuid=Alex:dev:+15550100001"


@pytest.fixture()
def door(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """A live door over a real state database; sends and dispatches recorded."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("OPENCLAW_WEBHOOK_SECRET", _BEARER)
    monkeypatch.setenv("SIGNAL_PEOPLE", _PEOPLE)
    monkeypatch.setenv(message_teammate._ENABLE_ENV, "1")
    monkeypatch.setenv("ASSISTANT_GITHUB_WRITE", "1")
    state.reset_for_tests()
    sent: list[str] = []
    dispatched: list[str] = []
    real_dispatch = mcp.write_tools.dispatch

    def _send(subject: str, message: str, recipient: str = "") -> bool:
        sent.append(message)
        return True

    def _dispatch(name, tool_input, actor):
        dispatched.append(name)
        if name == mcp.write_tools.GITHUB_ACT:
            return "commented on #151"
        return real_dispatch(name, tool_input, actor)

    monkeypatch.setattr(message_teammate._signal, "send", _send)
    monkeypatch.setattr(message_teammate._quiet_hours, "quiet_now", lambda: True)
    monkeypatch.setattr(mcp.write_tools, "dispatch", _dispatch)
    built = mcp.assistant_mcp_door()
    app = Starlette(
        routes=[Route("/mcp", built.asgi_app, methods=["POST"])],
        lifespan=built.lifespan,
    )
    with TestClient(app) as client:
        yield client, sent, dispatched


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


def test_a_worklist_item_assistant_opens_itself_is_recorded_as_assistants(door) -> None:
    """Owner and audit row both say assistant, not a teammate."""
    client, _sent, _dispatched = door
    answer = _call(
        client,
        "manage_worklist",
        {"action": "add", "kind": "watch", "title": "catering 47 agreement", "requested_by": f"{ASSISTANT_NAME}"},
    )
    assert "tracking as worklist item" in answer, answer
    owners = [item["owner"] for item in state.worklist.open_items()]
    assert owners == ["assistant"], owners
    door_rows = [row for row in state.assistant_actions.recent_actions() if row["kind"] == "door_write"]
    assert [row["actor"] for row in door_rows] == ["assistant"], door_rows


def test_a_message_assistant_starts_itself_is_held_by_quiet_hours(door) -> None:
    """The self-actor's hold comes with the name."""
    client, sent, _dispatched = door
    answer = _call(
        client,
        "message_teammate",
        {"person": "Alex", "message": "The supplier contract waits on you.", "requested_by": f"{ASSISTANT_NAME}"},
    )
    assert "quiet hours" in answer, answer
    assert sent == []


def test_a_board_write_booked_to_assistant_reaches_github_act(door) -> None:
    """the assistant on its own may work the board: the write is dispatched."""
    client, _sent, dispatched = door
    answer = _call(
        client,
        "github_act",
        {"action": "comment", "issue_number": 151, "body": "noted", "requested_by": f"{ASSISTANT_NAME}"},
    )
    assert mcp.write_tools.GITHUB_ACT in dispatched, answer
    assert "Nothing was written" not in answer, answer


def test_naming_assistant_still_cannot_create_a_video_call(door) -> None:
    """A person-only write booked to the assistant is refused undispatched."""
    client, _sent, dispatched = door
    answer = _call(
        client,
        "create_video_call",
        {"title": "y", "requested_by": f"{ASSISTANT_NAME}"},
    )
    assert mcp.write_tools.CREATE_VIDEO_CALL not in dispatched, answer
    assert "Nothing was written" in answer, answer
