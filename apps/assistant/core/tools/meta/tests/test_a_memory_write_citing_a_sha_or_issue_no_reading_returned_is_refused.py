"""A memory write citing a sha or an issue no reading returned is refused, and the assistant's own writes are not evidence.

WHAT IT PINS. Three seams. `write_tools.dispatch` of `remember_note` and
`manage_worklist` with an actor that carries what it read: a note or finding
citing a commit sha or a "#N" none of those readings held is refused and not
stored. The MCP door (`gates/mcp.py`): an answer that only repeats what the assistant
wrote is not kept as a reading, so it cannot back the next message, while
`github_act`'s answer, which carries the number of the issue it opened, still
is, and so is `manage_worklist` "list", whose titles carry issue numbers. And `message_teammate`: a sha no door answer held is refused.

WHY IT EXISTS. A patrol run can write "Deploy at 9abc1234, up to date" into
its journal while deploy_status says fedcba987654, copying a sha from an
earlier day; every later run then reads it as fact. And
the door kept "noted: <the note>" as a reading, so a number the assistant wrote into
its own memory backed its next message.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The
deploy_status text below holds
fedcba98 as a prefix of the full sha and does not hold 9abc1234. A number that
appears only in the assistant's own write was never returned by a tool, and an issue
GitHub numbered on create was.
"""
from __future__ import annotations

from apps.assistant.shared.name import ASSISTANT_NAME

import json

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from apps.assistant.core import state, tools
from apps.assistant.core.state import message_evidence
from apps.assistant.core.tools import write_tools
from apps.assistant.core.tools.team import message_teammate
from apps.assistant.gates import mcp

_DEPLOY_STATUS = (
    "Live deploy: fedcba9876543210fedcba9876543210fedcba98 "
    "(last success 2026-03-10 19:24:05)"
)
_BEARER = "door-test-bearer"
_PEOPLE = "uuid:alex-uuid=Alex:dev:+15550100001"


@pytest.fixture()
def db(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    state.reset_for_tests()


def _patrol_actor() -> write_tools.Actor:
    return write_tools.Actor(
        name="assistant", loop="patrol", evidence=lambda: [_DEPLOY_STATUS]
    )


def _journal() -> list[str]:
    return [note["text"] for note in state.recent_notes()]


def test_a_stale_sha_is_not_written_into_the_journal(db: None) -> None:
    """A sha copied from an earlier day is refused."""
    answer = write_tools.dispatch(
        "remember_note",
        {"note": "Deploy at 9abc1234, up to date."},
        _patrol_actor(),
    )
    assert answer.startswith("not recorded"), answer
    assert _journal() == [], "a sha no reading held went into memory"

    stored = write_tools.dispatch(
        "remember_note", {"note": "Deploy at fedcba98, up to date."}, _patrol_actor()
    )
    assert stored.startswith("noted:"), stored
    assert _journal() == ["Deploy at fedcba98, up to date."]


def test_a_worklist_finding_is_held_to_the_same_rule(db: None) -> None:
    item_id = state.worklist.add_item("watch", "Deploy health")
    answer = write_tools.dispatch(
        "manage_worklist",
        {"action": "progress", "item_id": item_id, "text": "Fixed by #4242."},
        _patrol_actor(),
    )
    assert answer.startswith("not recorded"), answer
    closed = write_tools.dispatch(
        "manage_worklist",
        {"action": "close", "item_id": item_id, "text": "Healthy at 9abc1234."},
        _patrol_actor(),
    )
    assert closed.startswith("not recorded"), closed
    assert [row["id"] for row in state.worklist.open_items()] == [item_id]


def test_a_phone_number_is_not_a_sha(db: None) -> None:
    answer = write_tools.dispatch(
        "remember_note",
        {"note": "Sam's number is 5550100123.", "person": "Sam"},
        _patrol_actor(),
    )
    assert answer.startswith("noted:"), answer


@pytest.fixture()
def door(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """A live door over a real state database, with every Signal send recorded."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "door.db"))
    monkeypatch.setenv("OPENCLAW_WEBHOOK_SECRET", _BEARER)
    monkeypatch.setenv("SIGNAL_PEOPLE", _PEOPLE)
    monkeypatch.setenv(message_teammate._ENABLE_ENV, "1")
    state.reset_for_tests()
    sent: list[str] = []

    def _send(subject: str, message: str, recipient: str = "") -> bool:
        sent.append(message)
        return True

    monkeypatch.setattr(message_teammate._signal, "send", _send)
    monkeypatch.setattr(message_teammate._quiet_hours, "quiet_now", lambda: False)
    monkeypatch.setattr(message_teammate, "_issue_facts", lambda number: "OPEN|0|0/0")
    monkeypatch.setattr(
        mcp.tools, "execute_typed", lambda name, arguments: tools.result.ok(name, _DEPLOY_STATUS)
    )
    monkeypatch.setattr(
        write_tools._gh_act,
        "execute",
        lambda tool_input, actor="assistant": (
            "done: created https://github.com/owner/repo/issues/4243"
        ),
    )
    built = mcp.assistant_mcp_door()
    app = Starlette(
        routes=[Route("/mcp", built.asgi_app, methods=["POST"])],
        lifespan=built.lifespan,
    )
    with TestClient(app) as client:
        yield client, sent


def _call(client: TestClient, tool: str, arguments: dict) -> str:
    response = client.post(
        "/mcp",
        headers={
            "authorization": f"Bearer {_BEARER}",
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
        },
        content=json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }),
    )
    assert response.status_code == 200, response.text
    return response.json()["result"]["content"][0]["text"]


def _tell_alex(client: TestClient, message: str) -> str:
    return _call(
        client, "message_teammate",
        {"person": "Alex", "message": message, "requested_by": "Alex"},
    )


def test_assistants_own_write_does_not_back_its_next_message(door) -> None:
    client, sent = door
    added = _call(
        client, "manage_worklist",
        {"action": "add", "kind": "watch", "title": "#4242 is the cause",
         "requested_by": f"{ASSISTANT_NAME}"},
    )
    assert "tracking as worklist item" in added, added
    answer = _tell_alex(client, "#4242 is the cause of the outage.")
    assert "not sent:" in answer and "#4242" in answer, answer
    assert sent == []


def test_an_issue_assistant_just_filed_still_backs_its_message(door) -> None:
    client, sent = door
    filed = _call(
        client, "github_act",
        {"action": "create", "title": "Probe side down", "requested_by": "Alex"},
    )
    assert "issues/4243" in filed, filed
    answer = _tell_alex(client, "Filed as #4243, the probe side is down.")
    assert "messaged Alex" in answer, answer
    assert len(sent) == 1


def test_a_message_citing_a_sha_nobody_read_is_refused(door) -> None:
    client, sent = door
    _call(client, "deploy_status", {})
    stale = _tell_alex(client, "Live deploy is 9abc1234.")
    assert "not sent:" in stale and "9abc1234" in stale, stale
    fresh = _tell_alex(client, "Live deploy is fedcba98.")
    assert "messaged Alex" in fresh, fresh


def test_the_worklist_read_through_the_door_backs_the_numbers_in_its_titles(door) -> None:
    """Listing the worklist is a reading, not an echo: its titles hold the
    issue numbers a brief chases (worklist item 40 names an issue)."""
    client, sent = door
    state.worklist.add_item("watch", "Printer has not answered on #38")
    listed = _call(
        client, "manage_worklist", {"action": "list", "requested_by": f"{ASSISTANT_NAME}"}
    )
    assert "#38" in listed, listed
    answer = _tell_alex(client, "#38: the printer has still not answered.")
    assert "messaged Alex" in answer, answer
    assert len(sent) == 1


def test_a_sha_past_the_excerpt_cut_still_backs_a_message(
    door, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A whats_changed answer runs to 40 commit lines and 40 issue lines, past
    the 2,000 characters a stored excerpt keeps; its last commit still counts."""
    client, sent = door
    commits = [
        f"- 2026-10-0{day % 9 + 1}T10:00:00Z {day:04d}abcdef openclaw: line {day} "
        + "of the change feed, long enough to fill the window"
        for day in range(39)
    ]
    feed = "\n".join([*commits, "- 2026-10-01T09:00:00Z 7e3f00c1d2 secret scan: fix"])
    assert feed.index("7e3f00c1d2") > message_evidence.MAX_EXCERPT_CHARS
    monkeypatch.setattr(
        mcp.tools, "execute_typed", lambda name, arguments: tools.result.ok(name, feed)
    )
    _call(client, "whats_changed", {"report_kind": "weekly"})
    answer = _tell_alex(client, "The secret scan was fixed in 7e3f00c1d2.")
    assert "messaged Alex" in answer, answer
    assert len(sent) == 1
