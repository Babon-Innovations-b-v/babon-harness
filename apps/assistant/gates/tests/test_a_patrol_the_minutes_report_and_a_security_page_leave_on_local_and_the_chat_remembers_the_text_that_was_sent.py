"""A patrol line, the minutes report and a security page leave on local time.

WHAT IT PINS. The `/webhook/patrol` and `/webhook/notulen` routes and
`core.security_sweep.sweep_security`, each with its model or filer stubbed and
its Signal send captured, then `core.sent_feed.sends_after`, the read the chat
relay copies into the chat. A "14:12 UTC" in the text a person gets must arrive
as local time, and the chat must remember the text that was sent.

WHY IT EXISTS. UTC times are rewritten at page_hold's release and in the pen's
own send, and these three roads send around both, so without this a person
would still read "14:12 UTC" in a patrol line or a security page.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The send moment
is pinned to 2026-10-22, inside the local summer time (UTC+2 until 25 October
2026), so 14:12 UTC is 16:12 there, read off the zone rules by hand.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

_SECRET = "test-bearer"
_ALEX = "+15550100012"
_UTC_LINE = "The blackbox forward hung at 14:12 UTC."
_LOCAL = "16:12 local"
_WHEN = datetime(2026, 10, 22, 15, 0, tzinfo=timezone.utc)


@pytest.fixture()
def pod(tmp_path, monkeypatch):
    """A fresh state DB, a bearer, a pinned clock and a send that lands and records its text."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.setenv("OPENCLAW_WEBHOOK_SECRET", _SECRET)
    monkeypatch.setenv("SIGNAL_PEOPLE", f"{_ALEX}=Alex:founder:{_ALEX}")
    monkeypatch.setenv("SIGNAL_RECIPIENT", _ALEX)
    from fastapi.testclient import TestClient

    from apps.assistant.core import state
    from apps.assistant.gates import app as gate_app
    from apps.assistant.shared import local_time

    state.reset_for_tests()
    sent: list[str] = []
    real_in_local_time = local_time.in_local_time
    monkeypatch.setattr(local_time, "in_local_time", lambda text, now=None: real_in_local_time(text, now or _WHEN))

    def land(body: str) -> bool:
        sent.append(body)
        return True

    monkeypatch.setattr(gate_app, "_send_beat", land)
    return SimpleNamespace(client=TestClient(gate_app.app), app=gate_app, sent=sent, state=state)


def _remembered_last() -> str:
    from apps.assistant.core import sent_feed

    return sent_feed.sends_after(0).sends[-1]["text"]


def test_a_patrol_line_leaves_on_local_time(pod, monkeypatch) -> None:
    """The patrol line the owner reads and the copy the chat keeps both say 16:12 local."""
    monkeypatch.setattr(pod.app.openclaw_issue_sweep, "sweep_orphan_issues", lambda: [])
    monkeypatch.setattr(pod.app.openclaw_recurring, "file_recurring_observations", lambda: [])
    monkeypatch.setattr(
        pod.app.openclaw_patrol, "patrol",
        lambda: SimpleNamespace(text=_UTC_LINE, worklist_items=[]),
    )
    response = pod.client.post("/webhook/patrol", headers={"Authorization": f"Bearer {_SECRET}"})
    assert response.status_code == 200, response.text
    assert pod.sent and _LOCAL in pod.sent[-1] and "UTC" not in pod.sent[-1], pod.sent
    assert _remembered_last() == pod.sent[-1]


def test_the_minutes_report_leaves_on_local_time(pod, monkeypatch) -> None:
    """The minutes report is rewritten before it is sent and remembered."""
    filed = SimpleNamespace(
        issues=[], root=None, updated=[], comments=[], problems=[],
        as_report=lambda title: f"Minutes of {title} filed. {_UTC_LINE}",
    )
    monkeypatch.setattr(pod.app.openclaw_notulen, "file_minutes", lambda *args: filed)
    response = pod.client.post(
        "/webhook/notulen",
        headers={"Authorization": f"Bearer {_SECRET}"},
        json={"job_id": "j1", "title": "Alex & Sam", "meeting_date": "2026-10-22", "markdown": "# notes"},
    )
    assert response.status_code == 200, response.text
    assert pod.sent and _LOCAL in pod.sent[-1] and "UTC" not in pod.sent[-1], pod.sent
    assert _remembered_last() == pod.sent[-1]


def test_a_security_page_leaves_on_local_time(pod, monkeypatch) -> None:
    """The security judgement's page is rewritten before it is sent and remembered."""
    from apps.assistant.core import security_sweep

    captured: list[str] = []
    monkeypatch.setattr(security_sweep.state, "count_since", lambda kind, minutes: 50)
    monkeypatch.setattr(security_sweep.state, "should_page", lambda key, seconds: True)
    monkeypatch.setattr(security_sweep.state, "recent_security_events", lambda minutes: [])
    monkeypatch.setattr(security_sweep._judge, "judge_security", lambda *args: _UTC_LINE)
    monkeypatch.setattr(
        security_sweep._signal, "send",
        lambda subject, body: captured.append(body) or True,
    )
    security_sweep.sweep_security()
    assert captured and _LOCAL in captured[-1] and "UTC" not in captured[-1], captured
    assert _remembered_last().endswith(captured[-1]), "the chat keeps a different text than was sent"
