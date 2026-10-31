"""An all-clear says the alert stopped firing and when, and never that the
problem is gone.

WHAT IT PINS. `core.triage.triage` across its public interface, with the firing
row written through `state.record_alert` as `gates/app` writes it. A resolve of
a paged alert is answered in code; this pins the words of that answer.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. A Prometheus
resolve means only that the rule's expression stopped returning the series, and
that also happens when the subject of the series is deleted. The
notulen-waiting rule matches a Pending pod, so releasing the container resolves it
while the meeting is still untranscribed. The draft therefore may
not carry any claim that the problem is over ("needs no action", "cleared",
"fixed", "resolved", "back to normal"). The clock it must name is the alert's
end, 2030-07-10 16:41 UTC, which is 18:41 in local summer time (UTC+2).
"""
from __future__ import annotations

import re

import pytest

_FINGERPRINT = "5e6f7a8b9c0d1e2f"
_SUMMARY = (
    "A meeting has waited 30 minutes for a GPU and is not being transcribed "
    "(example-warmup-job)."
)
_CLAIMS_THE_PROBLEM_IS_GONE = re.compile(
    r"needs no action|\bclear(ed)?\b|\bfixed\b|\bresolved\b|back to normal|all good",
    re.IGNORECASE,
)


@pytest.fixture()
def resolve_after_a_page(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    from apps.assistant.core import state
    from apps.assistant.core.triage import Alert, triage

    state.record_alert(
        fingerprint=_FINGERPRINT, name="TargetDown", severity="critical",
        status="firing", decision="enrich", reason="fixture",
        signal_sent=True, dead_letter=False,
    )
    return lambda: triage(Alert(
        fingerprint=_FINGERPRINT, status="resolved",
        labels={"alertname": "TargetDown", "severity": "critical",
                "kind": "notulen-waiting"},
        annotations={"summary": _SUMMARY},
        starts_at="2030-07-10T15:41:00Z", ends_at="2030-07-10T16:41:00Z",
    ))


def test_an_all_clear_says_when_the_alert_stopped_and_never_that_the_problem_is_gone(
    resolve_after_a_page,
) -> None:
    """It names the stop and its clock, and claims nothing about the problem."""
    draft = resolve_after_a_page().signal_draft

    assert draft, "a resolve of a delivered page must still reach the phone"
    assert "stopped firing" in draft.lower()
    assert "18:41" in draft
    found = _CLAIMS_THE_PROBLEM_IS_GONE.search(draft)
    assert not found, (
        f"the all-clear says {found.group(0)!r}, but an alert also stops when its "
        "subject goes away: the meeting was still waiting for a GPU"
    )
