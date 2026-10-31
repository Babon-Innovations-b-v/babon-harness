"""A failing Signal send backs off instead of retrying every pass.

WHAT IT PINS. `core.page_hold.release`, the only retrying sender in front of
the phone, across its public interface: a page goes in through
`state.hold_page`, the flusher's 30-second passes are calls to `release`, and
what Signal was asked to send is read off the list standing in for it. After a
failed send the next try waits 30 seconds, doubling to 15 minutes; the message
that finally lands opens with a line saying it is late and why, and the next
outage starts again from 30 seconds.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Twenty minutes
of passes, one every 30 seconds, with Signal refusing everything. Waits of 30,
60, 120, 240, 480 and 900 seconds put the tries at 0, 30, 90, 210, 450 and 930
seconds, and the next at 1830 is past the end: six sends and six not-delivered
rows, where retrying every pass is forty-one of each.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

_START = datetime(2026, 10, 7, 6, 0, 20, tzinfo=timezone.utc)


@pytest.fixture()
def signal(tmp_path, monkeypatch) -> dict:
    """A fresh queue with the clocks open, a fresh outage, and a Signal whose
    answer the test sets. Every gate and every read runs against SQLite."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.setenv("ASSISTANT_QUIET_HOURS", "off")
    from apps.assistant.core import page_hold

    monkeypatch.setattr(page_hold, "_outage", page_hold._SendOutage())
    wire: dict = {"up": False, "asked": [], "landed": []}

    def send(subject: str, body: str) -> bool:
        wire["asked"].append(body)
        if wire["up"]:
            wire["landed"].append(body)
        return wire["up"]

    monkeypatch.setattr(page_hold._signal_dispatch, "send", send)
    return wire


def _not_delivered_rows() -> int:
    from apps.assistant.core import state

    return sum(
        1 for row in state.list_recent_alerts(500) if row["decision"] == "not-delivered"
    )


def _passes(start: datetime, count: int) -> None:
    from apps.assistant.core import page_hold

    for step in range(count):
        page_hold.release(start + timedelta(seconds=30 * step))


def test_an_outage_costs_a_send_per_backoff_step_not_per_pass(signal) -> None:
    from apps.assistant.core import state

    state.hold_page("the night: 3 pings, all clear", road="pen", subject="the night")
    _passes(_START, 41)

    assert len(signal["asked"]) == 6, (
        f"{len(signal['asked'])} sends in 20 minutes of outage, not one per backoff step"
    )
    assert _not_delivered_rows() == 6, "each failed send writes exactly one row"


def test_the_late_message_says_so_and_the_next_outage_starts_short(signal) -> None:
    from apps.assistant.core import page_hold, state

    state.hold_page("the night: 3 pings, all clear", road="pen", subject="the night")
    _passes(_START, 41)

    signal["up"] = True
    back = _START + timedelta(seconds=1830)
    assert page_hold.release(back) is not None
    assert len(signal["landed"]) == 1
    assert signal["landed"][0].startswith("Late: Signal stopped delivering at 08:00"), (
        signal["landed"][0]
    )
    assert "the night: 3 pings, all clear" in signal["landed"][0]

    signal["up"] = False
    state.hold_page("a second page", road="pen", subject="later")
    later = back + timedelta(hours=1)
    asked = len(signal["asked"])
    _passes(later, 2)
    assert len(signal["asked"]) - asked == 2, (
        "the second outage inherited the first one's long wait"
    )
