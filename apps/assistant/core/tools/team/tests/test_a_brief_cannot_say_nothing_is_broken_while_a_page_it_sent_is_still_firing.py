"""A message saying nothing is broken is refused while an alert that paged still fires.

WHAT IT PINS. `message_teammate.execute`, at its public seam, reading the real
alerts table through `state.alerts.firing_paged_names`: an all-clear draft
comes back as a "not sent:" string naming the alert, and no Signal send is
attempted, whoever the send is booked to and however long ago the page went
out. Once the alert resolves the same draft goes out, and an everyday "all
good" that says nothing about the systems goes out while it fires. And the worklist block
the brief reads, `state.worklist.render`, no longer calls a fault the assistant is
looking into "not news" because it has sat still.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The draft is
a typical all-clear brief, and the alert is one that paged shortly before
it (a made-up alert name and fingerprint). The rows are written as the webhook writes them: a firing
arrival whose page reached a phone, a later firing re-send, then a resolve.
Whether an alert still fires is read off those rows by hand: the newest
arrival is firing, and nothing resolved it.
"""
from __future__ import annotations

import datetime as _datetime
from typing import Any

import pytest

from apps.assistant.core import state
from apps.assistant.core.state.conn import get_connection
from apps.assistant.core.tools.team import message_teammate

_BRIEF = (
    "Morning Alex. Nothing new for you today: everything up, deploy current, "
    "no calendar, no new issues, nothing broke overnight."
)
_FINGERPRINT = "359780fbd4f9c53c"


def _ago(**delta: float) -> str:
    return (_datetime.datetime.now(_datetime.timezone.utc) - _datetime.timedelta(**delta)).isoformat()


def _arrival(received_at: str, status: str, *, paged: bool) -> None:
    """One webhook arrival on the alert, written as `gates/app` writes it."""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO alerts (received_at, fingerprint, name, severity, status, "
            "decision, reason, signal_sent_at, dead_letter) "
            "VALUES (?, ?, 'TargetDown', 'warning', ?, ?, '', ?, 0)",
            (received_at, _FINGERPRINT, status, "page" if paged else "silent",
             received_at if paged else None),
        )
        conn.commit()


@pytest.fixture()
def sent(monkeypatch: pytest.MonkeyPatch, tmp_path) -> list[tuple[str, str, str]]:
    """Every Signal send this module attempts, recorded instead of sent, over a
    state database of the test's own."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    state.reset_for_tests()
    calls: list[tuple[str, str, str]] = []

    def _send(subject: str, message: str, recipient: str = "") -> bool:
        calls.append((subject, message, recipient))
        return True

    monkeypatch.setenv(message_teammate._ENABLE_ENV, "1")
    monkeypatch.setattr(message_teammate._signal, "send", _send)
    monkeypatch.setattr(message_teammate.people, "number_for", lambda person: "+15550100010")
    monkeypatch.setattr(message_teammate.people, "language_for", lambda person: "en")
    monkeypatch.setattr(message_teammate._quiet_hours, "quiet_now", lambda: False)
    monkeypatch.setattr(message_teammate.write_guard, "audit", lambda *a, **k: None)
    return calls


@pytest.mark.parametrize("actor", ["assistant", "Alex"])
def test_an_all_clear_is_refused_while_a_page_from_days_ago_still_fires(
    sent: list[Any], actor: str
) -> None:
    """Paged three days ago, re-sent firing since, never resolved."""
    _arrival(_ago(days=3), "firing", paged=True)
    _arrival(_ago(hours=1), "firing", paged=False)

    answer = message_teammate.execute({"person": "Alex", "message": _BRIEF}, actor=actor)

    assert answer.startswith("not sent:"), f"an all-clear went out over a firing page: {answer!r}"
    assert "TargetDown" in answer
    assert sent == []


def test_the_same_all_clear_goes_out_once_the_alert_resolved(sent: list[Any]) -> None:
    """The dangerous direction is silence: a fixed fault must not block the brief."""
    _arrival(_ago(hours=2), "firing", paged=True)
    _arrival(_ago(minutes=30), "resolved", paged=False)

    answer = message_teammate.execute({"person": "Alex", "message": _BRIEF}, actor="assistant")

    assert answer == "messaged Alex.", answer
    assert len(sent) == 1


@pytest.mark.parametrize("draft", ["All good, I'll book it.", "Sam, the invoice is all good."])
def test_an_everyday_all_good_goes_out_while_the_alert_fires(sent: list[Any], draft: str) -> None:
    """Only a claim about the systems is checked: an unrelated reply is not blocked."""
    _arrival(_ago(days=3), "firing", paged=True)
    _arrival(_ago(hours=1), "firing", paged=False)

    answer = message_teammate.execute({"person": "Alex", "message": draft}, actor="Alex")

    assert answer == "messaged Alex.", answer
    assert len(sent) == 1


def test_a_fault_assistant_is_looking_into_never_renders_as_not_news(sent: list[Any]) -> None:
    """The worklist half: a still fault stays open, a still watch stays quiet."""
    fault = state.worklist.add_item("look_into", "kube-state-metrics scrape down", owner="assistant")
    watch = state.worklist.add_item("watch", "Issue 27: backup restore test", owner="assistant")
    with get_connection() as conn:
        conn.execute("UPDATE worklist SET updated_at = ?, created_at = ?", (_ago(days=3), _ago(days=3)))
        conn.commit()

    lines = {
        line.split("]")[0].strip("- ["): line
        for line in state.worklist.render().splitlines()[1:]
    }

    assert "not news" not in lines[str(fault)]
    assert "take the next step" in lines[str(fault)]
    assert "not news" in lines[str(watch)]
