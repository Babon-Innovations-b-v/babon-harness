"""A resolve of a paged alert sends an all-clear, even inside the dedup window.

WHAT IT PINS. `core.triage.triage` and `core.page_hold.release`, across their
public interfaces, with the tables written through `state.record_alert` and
`state.hold_page` in the order `gates/app` writes them. A resolve whose firing
episode reached a phone is answered in code with an all-clear and no model
call; a resolve of a firing nobody heard about stays silent. The all-clear's
own delivery does not count as a page of the next firing episode.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Whether the
episode was paged is read off which rows the fixture recorded with
`signal_sent=True`; what reached the phone is the list standing in for it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

_FINGERPRINT = "a1b2c3d4e5f60718"
_NOON = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def pod(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.delenv("ASSISTANT_QUIET_HOURS", raising=False)
    monkeypatch.delenv("ASSISTANT_MORNING_GATE_UNTIL", raising=False)
    from apps.assistant.core import brain, page_hold, self_context, state, tools
    from apps.assistant.core.triage import Alert, triage

    calls: list[int] = []

    def fake_run(**_ignored):
        calls.append(1)
        submit = SimpleNamespace(
            type="tool_use", id="submit-1", name=tools.SUBMIT_NAME,
            input={"decision": "enrich", "reason": "down", "signal_draft": "Webapp is down."},
        )
        return brain.LoopOutcome("finished", SimpleNamespace(content=[submit]))

    landed: list[str] = []
    monkeypatch.setattr(brain, "run", fake_run)
    monkeypatch.setattr(self_context, "render", lambda loop, task: task)
    monkeypatch.setattr(
        page_hold._signal_dispatch, "send", lambda subject, body: landed.append(body) or True
    )

    def alert(status: str):
        return Alert(
            fingerprint=_FINGERPRINT, status=status,
            labels={"alertname": "ServiceDown", "severity": "warning"},
            annotations={"summary": "app.example.org probe failing"},
            starts_at="2026-10-18T13:53:00Z", ends_at="2026-10-18T14:02:25Z",
        )

    def arrival(status: str, *, delivered: bool = False) -> None:
        state.record_alert(
            fingerprint=_FINGERPRINT, name="ServiceDown", severity="warning",
            status=status, decision="enrich", reason="fixture",
            signal_sent=delivered, dead_letter=False,
        )

    def hold(text: str) -> None:
        state.hold_page(text, road="alertmanager", subject="ServiceDown",
                        severity="warning", key=_FINGERPRINT)

    return SimpleNamespace(
        triage=lambda status: triage(alert(status)), arrival=arrival, hold=hold,
        release=page_hold.release, calls=calls, landed=landed,
    )


def test_a_resolve_inside_the_dedup_window_of_a_delivered_page_is_an_all_clear(pod) -> None:
    pod.triage("firing")
    pod.arrival("firing", delivered=True)
    result = pod.triage("resolved")
    assert result.decision != "silent"
    assert result.reason.startswith("all-clear")
    assert result.signal_draft and result.signal_draft.startswith("Stopped firing")
    assert len(pod.calls) == 1


def test_a_resolve_of_a_firing_nobody_heard_about_stays_silent(pod) -> None:
    pod.arrival("firing")
    result = pod.triage("resolved")
    assert result.decision == "silent"
    assert not pod.calls


def test_the_all_clear_never_reads_as_the_next_episodes_page(pod) -> None:
    pod.hold("Webapp is down.")
    pod.arrival("firing")
    pod.release(now=_NOON)
    all_clear = pod.triage("resolved")
    pod.hold(all_clear.signal_draft)
    pod.arrival("resolved")
    pod.release(now=_NOON.replace(minute=20))
    pod.hold("Webapp is down again.")
    pod.arrival("firing")
    pod.release(now=_NOON.replace(minute=40))
    assert pod.landed[1].startswith("Stopped firing")
    assert pod.landed[-1] == "Webapp is down again."
