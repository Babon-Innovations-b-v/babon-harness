"""A held page the morning brief names is not sent again, and one it leaves out still is.

WHAT IT PINS. `core.page_hold.release`, the one wire in front of the phone,
across its public interface: pages go in through `state.hold_page`, the brief
lands as the row `message_teammate` writes after a delivered send (a
`teammate-self` chat turn to the page recipient), and what comes back is the
text that reached the phone. On a weekday the night waits past 08:00 for the
brief; once the brief has landed, a page it names is stamped released and
never sent, and a page it does not name leaves on its own. With no brief, the
night leaves when the wait runs out; on a Saturday it leaves at 08:00. The
pen's night page is queued under its batch's subjects and is carried only when
the brief names every one.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The owner's rule
 (held pages go in the morning report) plus the rule that
no page is ever lost, applied by reading each case: the brief text below
names "TargetDown" and not "ResourceHigh", so only the second may
reach the phone. 23 October 2026 is a Friday and 24 October a Saturday, both
on summer time, so 08:00 local is 06:00 UTC. The default wait is 30
minutes, so 08:15 still waits and 08:30 does not.
"""
from __future__ import annotations

from apps.assistant.shared.zone import LOCAL_ZONE

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

_LOCAL_TZ = LOCAL_ZONE
_ALEX = "+15550100001"
_DEGRADED = "TargetDown: signal-bridge metrics gone dark at 01:42."
_DISK = "ResourceHigh: the ops VM disk is at 88 percent."
_BRIEF = (
    "Today: standup 10:00. Held overnight: TargetDown, Fri 01:42 "
    "local, still dark."
)


@pytest.fixture()
def phone(tmp_path, monkeypatch) -> list[str]:
    """A fresh queue and a list standing in for the phone. Only the Signal
    send is replaced; every gate and every read runs against SQLite."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.setenv("SIGNAL_RECIPIENT", _ALEX)
    for name in ("ASSISTANT_QUIET_HOURS", "ASSISTANT_MORNING_GATE_UNTIL", "ASSISTANT_BRIEF_WAIT_MINUTES"):
        monkeypatch.delenv(name, raising=False)
    from apps.assistant.core import page_hold, state

    state.reset_for_tests()
    landed: list[str] = []
    monkeypatch.setattr(
        page_hold._signal_dispatch,
        "send",
        lambda subject, body: landed.append(body) or True,
    )
    return landed


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    """That October 2026 day at this local wall-clock time."""
    return datetime(2026, 10, day, hour, minute, tzinfo=_LOCAL_TZ)


def _night(day: int) -> None:
    """Two warnings held in the small hours, as triage holds them."""
    from apps.assistant.core import state

    for text, hour in ((_DEGRADED, 1), (_DISK, 3)):
        state.hold_page(
            text, road="alertmanager", subject=text.split(":")[0], severity="warning",
            now=_at(day, hour, 53).astimezone(timezone.utc).isoformat(),
        )


def _brief_lands(moment: datetime, text: str = _BRIEF) -> None:
    """The chat turn `message_teammate` writes once the brief is delivered."""
    from apps.assistant.core.state.conn import get_connection

    with get_connection() as conn:
        conn.execute(
            "INSERT INTO chat_turns (sender, role, text, created_at, loop) "
            "VALUES (?, 'assistant', ?, ?, 'teammate-self')",
            (_ALEX, text, moment.astimezone(timezone.utc).isoformat()),
        )
        conn.commit()


def _release(moment: datetime) -> str | None:
    from apps.assistant.core import page_hold

    return page_hold.release(moment)


def test_the_brief_carries_what_it_names_and_the_rest_still_leaves(phone) -> None:
    from apps.assistant.core import state

    _night(23)
    assert _release(_at(23, 8, 0)) is None and phone == [], (
        "on a weekday the night left at 08:00 instead of waiting for the brief"
    )

    _brief_lands(_at(23, 8, 4))
    _release(_at(23, 8, 5))

    assert phone == [_DISK], f"expected only the page the brief left out, got {phone}"
    assert state.pending_page_count() == 0, "a page the brief carried is still waiting"


def test_with_no_brief_the_night_leaves_when_the_wait_runs_out(phone) -> None:
    _night(23)

    assert _release(_at(23, 8, 15)) is None and phone == []
    _release(_at(23, 8, 30))

    assert len(phone) == 1 and _DEGRADED in phone[0] and _DISK in phone[0], (
        f"a weekday with no brief lost part of the night: {phone}"
    )


def test_a_saturday_night_leaves_at_eight(phone) -> None:
    _night(24)

    _release(_at(24, 8, 0))

    assert len(phone) == 1 and _DEGRADED in phone[0] and _DISK in phone[0], (
        f"a Saturday waited for a brief that never runs: {phone}"
    )


_PINGS = [
    {"subject": "auto-deploy: gate red on main"},
    {"subject": "batch done [nightly]"},
]
_PEN_PAGE = "Gate red at 02:10, batch done at 22:03."


@pytest.mark.parametrize(
    ("brief", "sent"),
    [
        ("Overnight: auto-deploy: gate red on main, 02:10.", [_PEN_PAGE]),
        (
            "Overnight: auto-deploy: gate red on main, 02:10; "
            "batch done [nightly], 22:03.",
            [],
        ),
    ],
)
def test_the_pens_night_page_is_carried_only_when_the_brief_names_each_subject(
    phone, brief, sent, monkeypatch
) -> None:
    """The pen queues its page under the batch's own subjects: a brief naming
    one of two does not carry it, a brief naming both does."""
    from apps.assistant.core import notify_flush
    from apps.assistant.core.state import page_hold as held_pages

    queued_at = _at(23, 7, 31).astimezone(timezone.utc).isoformat()
    monkeypatch.setattr(held_pages, "utcnow_iso", lambda: queued_at)
    notify_flush._hold_for_the_brief(_PEN_PAGE, _PINGS)
    _brief_lands(_at(23, 8, 3), brief)
    _release(_at(23, 8, 5))

    assert phone == sent, f"brief {brief!r} left the phone with {phone}"
