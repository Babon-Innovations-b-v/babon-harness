"""A page triage ties to a worklist item reaches the relay feed as concerning that item.

WHAT IT PINS. The whole page road at its public seams: `/webhook/alertmanager`
with `core.triage` behind it, the hold in `core.page_hold` and its `release`,
then `core.sent_feed.sends_after` (the read behind `GET /relay/sent`) and
`openclaw_watch.chat_relay.note`, the text the gateway's chat session reads.
The model is a stub that pages and names worklist item 36 in its submit.

WHY IT EXISTS. A page can go to the owner while triage's own reason says
"tracked on worklist item 36". If the page text leaves the item out and nothing
carries it, the owner's "done" is read as being about something else, item 36
stays open, and the next brief reads it as "Blind spot unchanged".

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The model
stub names item 36, which is open and the owner's. The send the relay reads must
concern 36, and the note must name the call that records a reply to it. A
second page whose submit names no item must reach the relay concerning nothing.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

_SECRET = "test-bearer"
_ALEX = "+15550100012"
_ITEM = 36


def _envelope(fingerprint: str) -> dict:
    return {
        "version": "4",
        "status": "firing",
        "alerts": [{
            "status": "firing",
            "labels": {
                "alertname": "TargetDown", "severity": "warning",
                "component": "secret-age", "secret": "anthropic-api-key",
            },
            "annotations": {"summary": "anthropic-api-key has no rotation date"},
            "startsAt": "2026-10-22T10:00:00Z", "endsAt": "0001-01-01T00:00:00Z",
            "fingerprint": fingerprint,
        }],
    }


@pytest.fixture()
def pod(tmp_path, monkeypatch):
    """A fresh state DB holding item 36, a model stub that pages, and a Signal stub."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.setenv("OPENCLAW_WEBHOOK_SECRET", _SECRET)
    monkeypatch.setenv("SIGNAL_PEOPLE", f"{_ALEX}=Alex:founder:{_ALEX}")
    monkeypatch.setenv("SIGNAL_RECIPIENT", _ALEX)
    from fastapi.testclient import TestClient

    from apps.assistant.core import brain, page_hold, self_context, state, tools
    from apps.assistant.gates import app as gate_app

    state.reset_for_tests()
    for number in range(1, _ITEM + 1):
        state.worklist.add_item("look_into", f"item {number}", owner="Alex")
    named: dict[str, object] = {"item": None}

    def fake_run(**_ignored):
        submit = SimpleNamespace(
            type="tool_use", id="submit-1", name=tools.SUBMIT_NAME,
            input={
                "decision": "enrich",
                "reason": "rotation date missing",
                "signal_draft": "anthropic-api-key has no rotation date, so its age alarm can never fire.",
                "worklist_item": named["item"],
            },
        )
        return brain.LoopOutcome("finished", SimpleNamespace(content=[submit]))

    monkeypatch.setattr(brain, "run", fake_run)
    monkeypatch.setattr(self_context, "render", lambda loop, task: task)
    monkeypatch.setattr(page_hold._signal_dispatch, "send", lambda **_ignored: True)
    client = TestClient(gate_app.app)

    def page(fingerprint: str, item: int | None) -> dict:
        """Post one alert whose page names `item`, release it, and return the relayed send."""
        named["item"] = item
        response = client.post(
            "/webhook/alertmanager", json=_envelope(fingerprint),
            headers={"Authorization": f"Bearer {_SECRET}"},
        )
        assert response.status_code == 200, response.text
        # 14:00 local on a Thursday: outside quiet hours and past the morning gate.
        page_hold.release(now=datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc))
        from apps.assistant.core import sent_feed

        return sent_feed.sends_after(0).sends[-1]

    return SimpleNamespace(page=page)


def test_a_page_about_item_36_reaches_the_relay_marked_as_concerning_36(pod) -> None:
    """The page's item rides from the submit to the note the chat reads."""
    from apps.assistant.watch import chat_relay

    send = pod.page("9dd4a93b4a18b053", _ITEM)
    assert [item["id"] for item in send["concerns"]] == [_ITEM], (
        f"the page reached the relay concerning {send['concerns']}; it must concern {_ITEM}"
    )
    note = chat_relay.note(send)
    assert f"record_answer with item_id {_ITEM}" in note, f"the note names no call: {note!r}"


def test_a_page_that_names_no_item_concerns_nothing(pod) -> None:
    """Control: a submit with no item gives a send with no item of its own."""
    send = pod.page("1c0ffee000000001", None)
    assert send["concerns"] == [], f"a page naming no item concerns {send['concerns']}"
