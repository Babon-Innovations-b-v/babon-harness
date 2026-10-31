"""Muting a noisy alertname must not silently mute the page under it.

WHAT IT PINS. `suppression.add_suppression`, at its public seam: a pattern that
also matches something which arrived critical inside the window raises
`CriticalUnderPattern` and writes nothing. A pattern that matches only
non-critical alerts is stored. `force=True` stores it anyway.

WHY IT EXISTS. An alertname is a rule group, not an incident, and this table
matches on the name. `ResourceHigh` is five Prometheus rules under one name,
from an info-level load observation up to the critical disk-full page. So
the obvious thing to type after a noisy week silences the page you most need:
a full filesystem, which can leave the assistant mute, is watched by one of
the five.
`recurring_alerts._recurring_subjects` already refuses to FILE an Alertmanager
subject for exactly this reason and argues it at length; nothing stopped a
person muting one by hand, which is the same mistake through the other door.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From the
table's own matching rule rather than from this function: `is_suppressed` asks
`? LIKE pattern`, so whatever that matches is what the mute covers. The test
builds two alerts under one name, one info and one critical, exactly the
`ResourceHigh` shape, and asks what muting the name would cover. The answer
comes from the LIKE semantics, not from reading the guard.

THE DANGEROUS DIRECTION IS A MUTE THAT DOES NOT HAPPEN, because an operator who
cannot silence a flake goes deaf a slower way. So two cases assert the mute
still lands: an ordinary flake pattern, and a deliberate `force`.
"""
from __future__ import annotations

import pytest

from apps.assistant.core import state
from apps.assistant.core.state import suppression


@pytest.fixture(autouse=True)
def _own_database(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    state.reset_for_tests()


def _arrived(name: str, severity: str) -> None:
    """One alert on the record, the only input the guard reads."""
    state.record_alert(
        fingerprint=f"{name}-{severity}",
        name=name,
        severity=severity,
        status="firing",
        decision="page",
        reason="test",
        signal_sent=True,
        dead_letter=None,
    )


def test_muting_a_rule_group_that_has_paged_critical_is_refused() -> None:
    """The ResourceHigh shape: one name, an observation and a page."""
    _arrived("ResourceHigh", "info")
    _arrived("ResourceHigh", "critical")

    with pytest.raises(suppression.CriticalUnderPattern) as refused:
        suppression.add_suppression("ResourceHigh", "noisy", added_by="alex")

    assert "ResourceHigh" in str(refused.value)
    assert suppression.is_suppressed("ResourceHigh") == (False, None), (
        "the mute was written despite the refusal, so the page is gone"
    )


def test_muting_a_flake_still_works() -> None:
    """The ordinary case, and the reason this guard must stay narrow."""
    _arrived("backup-freshness-probe", "warning")
    suppression.add_suppression("backup-freshness-%", "known flake")
    suppressed, reason = suppression.is_suppressed("backup-freshness-probe")
    assert suppressed and reason == "known flake"


def test_force_means_the_person_meant_it() -> None:
    """A refusal that cannot be overridden is a guard that gets worked around."""
    _arrived("ResourceHigh", "critical")
    suppression.add_suppression("ResourceHigh", "really", force=True)
    assert suppression.is_suppressed("ResourceHigh")[0]


def test_a_pattern_matching_nothing_is_allowed_quietly() -> None:
    """Muting ahead of a known noisy deploy must not need a ceremony."""
    suppression.add_suppression("something-that-never-fired-%", "pre-emptive")
    assert suppression.is_suppressed("something-that-never-fired-yet")[0]
