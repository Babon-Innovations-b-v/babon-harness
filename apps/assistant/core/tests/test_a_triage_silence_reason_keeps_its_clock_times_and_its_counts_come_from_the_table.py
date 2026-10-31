"""A triage silence reason keeps its clock times, and its counts come from the
table.

WHAT IT PINS. `core.triage.triage` across its public interface, with the model
stubbed and the alerts table seeded through `state.record_alert`. A silence
that stands is stored with the model's words as they came, after the time code
read. The page history the model is shown gives the delivery in local time
and how many judged silences followed it, counted by code.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The delivery
is pinned at 2026-06-11T19:14Z, which is 21:14 in local under CEST. After
it the fixture writes three judged silences and one dedup-window hit, which is
mechanical and not a judgement: three.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

_FINGERPRINT = "9c620cfb66dd863e"
_REASON = "Already paged on 2026-06-11 at 19:14. Silenced every cycle today (06:28, 10:28, 14:28)."


@pytest.fixture()
def pod(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    from apps.assistant.core import brain, self_context, state, tools
    from apps.assistant.core.state.conn import get_connection
    from apps.assistant.core.triage import Alert, triage

    delivered = state.record_alert(
        fingerprint=_FINGERPRINT, name="TargetDown", severity="warning",
        status="firing", decision="released", reason="page_hold release",
        signal_sent=True, dead_letter=False,
    )
    with get_connection() as conn:
        conn.execute(
            "UPDATE alerts SET received_at = ?, signal_sent_at = ? WHERE id = ?",
            ("2026-06-11T19:14:00+00:00", "2026-06-11T19:14:00+00:00", delivered),
        )
        conn.commit()
    for reason in ("judged", "judged", "judged", "dedup-window-hit"):
        state.record_alert(
            fingerprint=_FINGERPRINT, name="TargetDown", severity="warning",
            status="firing", decision="silent", reason=reason,
            signal_sent=False, dead_letter=False,
        )
    shown: list[str] = []

    def fake_run(*, messages, **_ignored):
        shown.append(messages[0]["content"])
        submit = SimpleNamespace(
            type="tool_use", id="submit-1", name=tools.SUBMIT_NAME,
            input={"decision": "silent", "reason": _REASON, "signal_draft": None},
        )
        return brain.LoopOutcome("finished", SimpleNamespace(content=[submit]))

    monkeypatch.setattr(brain, "run", fake_run)
    monkeypatch.setattr(self_context, "render", lambda loop, task: task)
    result = triage(
        Alert(
            fingerprint=_FINGERPRINT, status="firing",
            labels={"alertname": "TargetDown", "severity": "warning"},
            annotations={"summary": "No alert has been proved to reach a phone"},
            starts_at="2026-06-11T13:12:00Z", ends_at="0001-01-01T00:00:00Z",
        )
    )
    return SimpleNamespace(result=result, shown=shown)


def test_the_stored_reason_keeps_the_models_clock_times(pod) -> None:
    assert pod.result.decision == "silent"
    assert "at 19:14." in pod.result.reason
    assert "(06:28, 10:28, 14:28)" in pod.result.reason


def test_the_page_history_gives_local_time_and_a_counted_total(pod) -> None:
    assert "21:14 local time" in pod.shown[0]
    assert "silenced 3 times since" in pod.shown[0]
