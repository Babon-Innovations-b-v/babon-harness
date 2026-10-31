"""A held page that is no longer news never reaches the phone.

WHAT IT PINS. `core.page_hold.release`, the single wire in front of both of
The assistant's roads to a phone, across its public interface: pages go into the queue
through `state.hold_page`, arrivals through `state.record_alert` in the order
`gates/app` writes them (the page is held, then its own arrival is audited), and
what comes back is the text that reached the phone. A keyed page whose alert
resolved before it left is dropped, and so is a second page in one firing
episode. A flap, a page saying the thing came back, a new episode after a
resolve and a keyless page all still go.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Each case is a
short history on one fingerprint written out by hand, and the rule applied to it
by reading it: the newest arrival after the hold is a resolve (and the page's
own arrival was not) means the page is stale; a delivered page on the key with
no resolve after it means this episode was already said. Whether a page reached
the phone is read off the list standing in for the phone.
"""
from __future__ import annotations

from apps.assistant.shared.zone import LOCAL_ZONE

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

_LOCAL_TZ = LOCAL_ZONE
_KEY = "4405b24e6462f486"
_PAGE = "TargetDown: signal-bridge metrics gone dark."


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


def _morning(minutes_after_eight: int = 0) -> datetime:
    """08:00 local today plus some minutes: past quiet hours and the
    morning gate, and ten minutes apart is past the five-minute story gap."""
    eight = datetime.now(_LOCAL_TZ).replace(hour=8, minute=0, second=0, microsecond=0)
    return eight + timedelta(minutes=minutes_after_eight)


def _page(text: str = _PAGE, *, status: str = "firing", key: str = _KEY) -> None:
    """One page as `gates/app` writes it: held first, then its arrival audited."""
    from apps.assistant.core import state

    state.hold_page(text, road="alertmanager" if key else "pen",
                    subject="TargetDown", severity="warning", key=key)
    if key:
        _arrival(status)


def _arrival(status: str) -> None:
    from apps.assistant.core import state

    state.record_alert(
        fingerprint=_KEY, name="TargetDown", severity="warning",
        status=status, decision="enrich" if status == "firing" else "silent",
        reason="fixture", signal_sent=False, dead_letter=False,
    )


def _release(minutes_after_eight: int = 0) -> str | None:
    from apps.assistant.core import page_hold

    return page_hold.release(_morning(minutes_after_eight))


def test_a_page_whose_alert_resolved_before_it_left_is_dropped(phone) -> None:
    """Held, then the resolve, then the morning."""
    from apps.assistant.core import state

    _page()
    _arrival("resolved")

    assert _release() is None and phone == [], (
        "a page about an outage that had already ended reached the phone"
    )
    assert state.pending_page_count() == 0, "the stale page is still waiting"
    assert state.last_release_at() is None, "a dropped page moved the pacing clock"


def test_a_flap_is_still_firing_and_still_pages(phone) -> None:
    """Resolved and firing again before the morning is firing at breakfast."""
    _page()
    _arrival("resolved")
    _arrival("firing")

    assert _release() is not None and len(phone) == 1


def test_a_page_saying_the_thing_came_back_is_not_stale(phone) -> None:
    """Its own arrival was the resolve, so the resolve cannot make it stale."""
    _page("signal-bridge is publishing again.", status="resolved")

    assert _release() is not None and len(phone) == 1


def test_one_firing_episode_pages_once_and_a_new_one_pages_again(phone) -> None:
    """The same unresolved alert, three mornings."""
    _page()
    assert _release(0) is not None, "the first page of the episode never left"

    _page(_PAGE + " Still dark.")
    _arrival("firing")
    assert _release(10) is None and len(phone) == 1, (
        "a second page in one unresolved firing episode reached the phone"
    )

    _arrival("resolved")
    _page(_PAGE + " Dark again.")
    assert _release(20) is not None and len(phone) == 2, (
        "a firing that started after a resolve was taken for the old episode"
    )


def test_a_page_with_no_fingerprint_is_never_dropped(phone) -> None:
    """The pen's merged night carries no identity to ask about."""
    _page("the night: 24 pings, the deploy queue is red", key="")
    _arrival("resolved")

    assert _release() is not None and len(phone) == 1
