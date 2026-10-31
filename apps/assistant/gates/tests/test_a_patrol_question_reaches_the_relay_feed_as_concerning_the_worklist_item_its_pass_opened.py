"""A patrol question reaches the relay feed as concerning the worklist item its pass opened.

WHAT IT PINS. The `/webhook/patrol` route with `core.patrol.patrol` behind it,
the real `manage_worklist` write a pass makes, then `core.sent_feed.sends_after`
(the read behind `GET /relay/sent`) and `openclaw_watch.chat_relay.note`. The
model is a stub that files a watch item as bookkeeping, then files one
question and asks it; the send to Signal is a stub that lands.

WHY IT EXISTS. Patrol files the question it asks on the worklist so it
remembers it asked, and a reply closes that question only through
`record_answer`, which needs the item's id. When nothing carries the id to
the chat that hears the reply, `record_answer` is never called.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The id comes
from the worklist write itself, read back off `manage_worklist`'s own answer
inside the stub. An older open item the pass never touched, and the watch
item the same pass filed, are the ones the send must not concern: a reply can
answer only the question.

The watch item was proved by hand against `patrol._dispatch_tracked` keeping
every item a pass opened, whatever its kind: the send then concerns both.
"""
from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

_SECRET = "test-bearer"
_ALEX = "+15550100012"
_QUESTION = "Should the nightly backup keep 14 days or 30?"


@pytest.fixture()
def pod(tmp_path, monkeypatch):
    """A fresh state DB, a bearer, a patrol model stub that files and asks, and a landing send."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.setenv("OPENCLAW_WEBHOOK_SECRET", _SECRET)
    monkeypatch.setenv("SIGNAL_PEOPLE", f"{_ALEX}=Alex:founder:{_ALEX}")
    monkeypatch.setenv("SIGNAL_RECIPIENT", _ALEX)
    from fastapi.testclient import TestClient

    from apps.assistant.core import patrol, state
    from apps.assistant.gates import app as gate_app

    state.reset_for_tests()
    untouched = state.worklist.add_item("watch", "Registry size", owner="Alex")
    filed: dict[str, int] = {}

    def fake_run(**kwargs):
        bookkeeping = kwargs["dispatch"](
            "manage_worklist",
            {"action": "add", "kind": "watch", "title": "Backup bucket size"},
        )
        filed["watch"] = int(re.search(r"worklist item (\d+)", bookkeeping).group(1))
        answer = kwargs["dispatch"](
            "manage_worklist",
            {"action": "add", "kind": "question", "title": "Backup retention: 14 or 30 days"},
        )
        filed["id"] = int(re.search(r"worklist item (\d+)", answer).group(1))
        return SimpleNamespace(
            finished=True,
            status="finished",
            response=SimpleNamespace(content=[SimpleNamespace(type="text", text=_QUESTION)]),
        )

    monkeypatch.setattr(patrol._brain, "run", fake_run)
    monkeypatch.setattr(patrol._self_context, "render", lambda *a, **k: "system")
    monkeypatch.setattr(patrol._quiet_hours, "quiet_now", lambda *a, **k: False)
    monkeypatch.setattr(gate_app.openclaw_issue_sweep, "sweep_orphan_issues", lambda: [])
    monkeypatch.setattr(gate_app.openclaw_recurring, "file_recurring_observations", lambda: [])
    monkeypatch.setattr(gate_app, "_send_beat", lambda body: True)
    client = TestClient(gate_app.app)
    return SimpleNamespace(client=client, filed=filed, untouched=untouched)


def test_the_question_reaches_the_relay_concerning_the_item_it_filed(pod) -> None:
    """The item the pass opened rides with its line to the note the chat reads."""
    from apps.assistant.watch import chat_relay
    from apps.assistant.core import sent_feed

    response = pod.client.post("/webhook/patrol", headers={"Authorization": f"Bearer {_SECRET}"})
    assert response.status_code == 200 and response.json()["sent"], response.text

    send = sent_feed.sends_after(0).sends[-1]
    assert send["text"] == _QUESTION, send
    assert [item["id"] for item in send["concerns"]] == [pod.filed["id"]], (
        f"the patrol question concerns {send['concerns']}; it must concern the "
        f"item its pass opened, {pod.filed['id']}"
    )
    note = chat_relay.note(send)
    assert f"record_answer with item_id {pod.filed['id']}" in note, note
    assert f"[{pod.untouched}]" not in note, f"the note offers the untouched item: {note!r}"
    assert f"item_id {pod.filed['watch']}" not in note, (
        f"the note names the watch item the pass filed as bookkeeping: {note!r}"
    )
