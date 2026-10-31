"""A triage silence never cites a page its fingerprint never delivered.

WHAT IT PINS. `core.triage.triage` and `core.awareness.render`, across their
public interfaces, with the alerts table seeded through `state.record_alert`.
A silence whose reason claims a page ("already paged and delivered at 13:40")
stands only when the table shows a delivered page on this fingerprint, or on
the fingerprint the model named as the covering page; otherwise it becomes a
raw page. The model is told this fingerprint's own page history, read by
code, and the awareness rows say which fingerprint each line is about.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The fixture is
two fingerprints of one alert name: A, textfile,
one row with `signal_sent_at` set; B, gate-full-audit, only silent rows with
`signal_sent_at` NULL. Whether a page was delivered is read off the fixture by
looking at which rows were recorded with `signal_sent=True`, and nothing else.
The time the model claims, 03:17 UTC, is chosen so that it is never the time
the table holds: code renders a delivery as `YYYY-MM-DDTHH:MMZ`, never with
" UTC" after it.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

_COST_AUDIT = "99a55c63aa11bb22"
_GATE_AUDIT = "63670a81cc33dd44"
_CLAIM = "same dead textfile service already paged and delivered at 03:17 UTC"


def _seed(state) -> None:
    """A delivered on its own fingerprint, B never."""
    state.record_alert(
        fingerprint=_COST_AUDIT, name="UnitFailed", severity="warning",
        status="firing", decision="released", reason="page_hold release",
        signal_sent=True, dead_letter=False,
    )
    for _ in range(2):
        state.record_alert(
            fingerprint=_GATE_AUDIT, name="UnitFailed", severity="warning",
            status="firing", decision="silent", reason=_CLAIM,
            signal_sent=False, dead_letter=False,
        )


@pytest.fixture()
def submit_silence(tmp_path, monkeypatch):
    """A fresh table with the two fingerprints, and a model stub that silences
    with the claim, optionally naming a covering fingerprint. Returns a call
    that triages one alert and the list of user messages the model was shown."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    from apps.assistant.core import brain, self_context, state, tools
    from apps.assistant.core.triage import Alert, triage

    _seed(state)
    shown: list[str] = []
    covering: dict[str, str | None] = {"fingerprint": None}

    def fake_run(*, messages, **_ignored):
        shown.append(messages[0]["content"])
        submit = SimpleNamespace(
            type="tool_use", id="submit-1", name=tools.SUBMIT_NAME,
            input={
                "decision": "silent", "reason": _CLAIM, "signal_draft": None,
                "covered_by_fingerprint": covering["fingerprint"],
            },
        )
        return brain.LoopOutcome("finished", SimpleNamespace(content=[submit]))

    monkeypatch.setattr(brain, "run", fake_run)
    monkeypatch.setattr(self_context, "render", lambda loop, task: task)

    def run(fingerprint: str, covered_by: str | None = None):
        covering["fingerprint"] = covered_by
        alert = Alert(
            fingerprint=fingerprint, status="firing",
            labels={"alertname": "UnitFailed", "severity": "warning"},
            annotations={"summary": "a systemd unit on the ops VM failed"},
            starts_at="2026-08-31T21:40:00Z", ends_at="0001-01-01T00:00:00Z",
        )
        return triage(alert)

    return SimpleNamespace(run=run, shown=shown, state=state)


def test_a_claimed_page_on_a_fingerprint_that_never_delivered_pages(submit_silence) -> None:
    result = submit_silence.run(_GATE_AUDIT)
    assert result.decision == "page-raw"
    assert result.signal_draft
    assert "has ever reached a phone" in submit_silence.shown[0]


def test_a_claimed_page_that_was_delivered_stands_with_the_time_code_read(submit_silence) -> None:
    delivered = next(
        row["signal_sent_at"]
        for row in submit_silence.state.list_recent_alerts(10)
        if row["fingerprint"] == _COST_AUDIT and row["signal_sent_at"]
    )
    result = submit_silence.run(_COST_AUDIT)
    assert result.decision == "silent"
    assert delivered
    # The time code read leads; the model's own words follow, quoted as they
    # came and labelled as the model's.
    assert result.reason.startswith(
        f"repeat; last delivered on this fingerprint at {delivered[:16]}Z (model said: "
    )
    assert f"last delivered to a phone at {delivered[:16]}Z" in submit_silence.shown[0]


def test_cover_by_another_page_stands_only_when_that_page_was_delivered(submit_silence) -> None:
    covered = submit_silence.run(_GATE_AUDIT, covered_by=_COST_AUDIT)
    assert covered.decision == "silent"
    assert _COST_AUDIT in covered.reason


def test_the_awareness_rows_tell_two_alerts_of_one_name_apart(submit_silence) -> None:
    from apps.assistant.core import awareness

    picture = awareness.render()
    assert f"UnitFailed [{_COST_AUDIT}]" in picture
    assert f"UnitFailed [{_GATE_AUDIT}]" in picture
