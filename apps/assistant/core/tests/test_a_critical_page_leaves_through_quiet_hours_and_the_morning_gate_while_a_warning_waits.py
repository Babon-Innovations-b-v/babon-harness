"""A critical page leaves through quiet hours and the morning gate while a warning waits.

WHAT IT PINS. `core.page_hold.release`, the one wire in front of the phone,
across its public interface: pages go in through `state.hold_page` with the
severity `gates/app._hold_page` copies off the alert, arrivals through
`state.record_alert` in the order `gates/app` writes them, and what comes back
is the text that reached the phone. At 02:00 and at 07:45 local a critical
page leaves at once and alone; the warning held beside it waits for 08:00. A
critical whose alert resolved before the pass is still dropped.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The paging rule,
applied by reading each case: the default quiet window is
22:00-07:30 and the morning gate holds until 08:00, so 02:00 and 07:45 are both
held moments and 08:00 is not; a critical goes through either hold, anything
else does not. Whether a page reached the phone is read off the list standing in
for the phone.
"""
from __future__ import annotations

from apps.assistant.shared.zone import LOCAL_ZONE

from datetime import datetime

import pytest
from zoneinfo import ZoneInfo

_LOCAL_TZ = LOCAL_ZONE
_CRITICAL_FINGERPRINT = "c1a2b3c4d5e6f708"
_WARNING_FINGERPRINT = "4405b24e6462f486"
_CRITICAL = "UnitFailed: the deploy gate is red and nothing is shipping."
_WARNING = "TargetDown: signal-bridge metrics gone dark."


@pytest.fixture()
def phone(tmp_path, monkeypatch) -> list[str]:
    """A fresh queue and a list standing in for the phone. Only the Signal
    send is replaced; every gate and every read runs against SQLite."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.delenv("ASSISTANT_QUIET_HOURS", raising=False)
    monkeypatch.delenv("ASSISTANT_MORNING_GATE_UNTIL", raising=False)
    # No wait for the weekday brief: these cases pin the gate's clock,
    # and the brief carrying the night is pinned on its own.
    monkeypatch.setenv("ASSISTANT_BRIEF_WAIT_MINUTES", "0")
    from apps.assistant.core import page_hold

    landed: list[str] = []
    monkeypatch.setattr(
        page_hold._signal_dispatch,
        "send",
        lambda subject, body: landed.append(body) or True,
    )
    return landed


def _at(hour: int, minute: int = 0) -> datetime:
    """Today at this local time."""
    return datetime.now(_LOCAL_TZ).replace(hour=hour, minute=minute, second=0, microsecond=0)


def _page(text: str, *, key: str, severity: str, status: str = "firing") -> None:
    """One page as `gates/app` writes it: held first, then its arrival audited."""
    from apps.assistant.core import state

    state.hold_page(text, road="alertmanager", subject=text.split(":")[0],
                    severity=severity, key=key)
    _arrival(key, severity, status)


def _arrival(key: str, severity: str, status: str) -> None:
    from apps.assistant.core import state

    state.record_alert(
        fingerprint=key, name="fixture", severity=severity, status=status,
        decision="enrich" if status == "firing" else "silent",
        reason="fixture", signal_sent=False, dead_letter=False,
    )


def _release(moment: datetime) -> str | None:
    from apps.assistant.core import page_hold

    return page_hold.release(moment)


@pytest.mark.parametrize(("hour", "minute"), [(2, 0), (7, 45)])
def test_a_critical_leaves_inside_the_hold_and_the_warning_waits(phone, hour, minute) -> None:
    """Quiet hours (02:00) and the morning gate (07:45) both let a critical out."""
    _page(_WARNING, key=_WARNING_FINGERPRINT, severity="warning")
    _page(_CRITICAL, key=_CRITICAL_FINGERPRINT, severity="critical")

    assert _release(_at(hour, minute)) == _CRITICAL and phone == [_CRITICAL], (
        f"at {hour:02d}:{minute:02d} the critical page did not leave alone"
    )

    assert _release(_at(8, 0)) == _WARNING and phone == [_CRITICAL, _WARNING], (
        "the warning did not wait for the morning, or the critical left twice"
    )


def test_a_warning_alone_is_still_held_through_the_night(phone) -> None:
    """Nothing critical waiting means the hold is exactly what it was."""
    _page(_WARNING, key=_WARNING_FINGERPRINT, severity="warning")

    assert _release(_at(2, 0)) is None and phone == []


def test_a_critical_whose_alert_resolved_is_still_dropped(phone) -> None:
    """Going through the night does not skip the already-resolved check."""
    from apps.assistant.core import state

    _page(_CRITICAL, key=_CRITICAL_FINGERPRINT, severity="critical")
    _arrival(_CRITICAL_FINGERPRINT, "critical", "resolved")

    assert _release(_at(2, 0)) is None and phone == []
    assert state.pending_page_count() == 0, "the resolved critical is still waiting"
