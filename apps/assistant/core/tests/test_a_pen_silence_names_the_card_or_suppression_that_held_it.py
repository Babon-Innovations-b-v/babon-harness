"""A pen silence names the card or suppression that held it.

WHAT IT PINS. `core.notify_flush.flush_pen` across its public seams: pings go
in through `state.enqueue_ping`, the mutes through `state.record_filed` and
`state.add_suppression`, and the answer is read off the `alerts` row the flush
writes. When the pen drops a ping because its subject is filed or suppressed,
that row says which card or which human suppression held it, not only how many
pings there were.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Two pings,
written by hand: the reverted-on-main ping whose
subject was filed as an issue, and an auth-journey probe failure filed as an issue.
Both cards are the test's own inserts, so the row must name an issue and an issue. A
third run holds one ping under a suppression whose reason is the test's own
sentence, so the row must carry that sentence.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

_REVERT = "\U0001f534 auto-deploy: a commit was reverted on main"
_PROBE = "systemd unit failed: harness-auth-journey-probe.service"
# 14:00 local: outside quiet hours and the morning gate.
_AFTERNOON = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def state(tmp_path, monkeypatch):
    """A fresh state file of this test's own; nothing leaves the box."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.delenv("ASSISTANT_QUIET_HOURS", raising=False)
    from apps.assistant.core import state as state_module

    return state_module


def _silenced_reason(state) -> str:
    rows = [
        row for row in state.list_recent_alerts(50) if row["decision"] == "batch-silenced"
    ]
    assert len(rows) == 1, f"expected one batch-silenced row, got {len(rows)}"
    return str(rows[0]["reason"])


def test_a_filed_silence_names_its_cards(state) -> None:
    from apps.assistant.core import notify_flush

    state.record_filed("auto-deploy: a commit was reverted on main", 41)
    state.record_filed(_PROBE, 42)
    state.enqueue_ping(_REVERT, "eject reverted abc123", "notify")
    state.enqueue_ping(_PROBE, "journey broken at mfa_challenge", "notify")

    assert notify_flush.flush_pen(_AFTERNOON) is None
    reason = _silenced_reason(state)
    assert "#41" in reason and "#42" in reason, (
        f"the silenced row does not say which card held it: {reason!r}"
    )


def test_a_suppressed_silence_names_the_suppression(state) -> None:
    from apps.assistant.core import notify_flush

    state.add_suppression(_PROBE, "Alex: single probe blips, AuthJourneyBroken covers it")
    state.enqueue_ping(_PROBE, "login answered http 502", "notify")

    assert notify_flush.flush_pen(_AFTERNOON) is None
    reason = _silenced_reason(state)
    assert "single probe blips" in reason, (
        f"the silenced row does not say which suppression held it: {reason!r}"
    )
