"""A covering page triage reads off the awareness rows is one the claim gate can find.

WHAT IT PINS. `core.awareness.render` and `core.triage.triage`, across their
public interfaces, with the alerts table seeded through `state.record_alert`.
A silence that names another alert's page as `covered_by_fingerprint` stands
only when that fingerprint delivered, and the gate checks it by an exact match.
The awareness rows are the only place in triage's prompt that carries another
alert's fingerprint, so the fingerprint the model copies from them has to be
one the gate can find.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The fixture has
two fingerprints of one alert name: textfile, recorded once with
`signal_sent=True` (delivered, decision `released`), and gate-full-audit, never
delivered. The test plays the model: it reads the fingerprint printed on the
`released` row of the rendered awareness picture, exactly as the model would,
and names it as the covering page. Since textfile really delivered, the
silence on gate-full-audit must stand.
"""
from __future__ import annotations

import re
from types import SimpleNamespace

_COST_AUDIT = "99a55c63aa11bb22"
_GATE_AUDIT = "63670a81cc33dd44"
_CLAIM = "same dead textfile service already paged"
_RELEASED_ROW = re.compile(r"UnitFailed \[([^\]]+)\] -> released")


def _seed(state) -> None:
    """Cost-audit delivered on its own fingerprint, gate-full-audit never."""
    state.record_alert(
        fingerprint=_COST_AUDIT, name="UnitFailed", severity="warning",
        status="firing", decision="released", reason="page_hold release",
        signal_sent=True, dead_letter=False,
    )
    state.record_alert(
        fingerprint=_GATE_AUDIT, name="UnitFailed", severity="warning",
        status="firing", decision="silent", reason=_CLAIM,
        signal_sent=False, dead_letter=False,
    )


def test_a_covering_page_triage_reads_off_the_awareness_rows_is_one_the_claim_gate_can_find(
    tmp_path, monkeypatch
) -> None:
    """The fingerprint copied off the delivered row covers the silence."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    from apps.assistant.core import awareness, brain, self_context, state, tools
    from apps.assistant.core.triage import Alert, triage

    _seed(state)
    shown_fingerprints = _RELEASED_ROW.findall(awareness.render())
    assert len(shown_fingerprints) == 1
    named = shown_fingerprints[0]

    def fake_run(*, messages, **_ignored):
        submit = SimpleNamespace(
            type="tool_use", id="submit-1", name=tools.SUBMIT_NAME,
            input={
                "decision": "silent", "reason": _CLAIM, "signal_draft": None,
                "covered_by_fingerprint": named,
            },
        )
        return brain.LoopOutcome("finished", SimpleNamespace(content=[submit]))

    monkeypatch.setattr(brain, "run", fake_run)
    monkeypatch.setattr(self_context, "render", lambda loop, task: task)
    result = triage(
        Alert(
            fingerprint=_GATE_AUDIT, status="firing",
            labels={"alertname": "UnitFailed", "severity": "warning"},
            annotations={"summary": "a systemd unit on the ops VM failed"},
            starts_at="2026-08-31T21:40:00Z", ends_at="0001-01-01T00:00:00Z",
        )
    )
    assert result.decision == "silent"
