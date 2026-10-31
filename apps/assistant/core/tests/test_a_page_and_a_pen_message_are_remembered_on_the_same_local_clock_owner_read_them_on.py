"""A page and a pen message are remembered on the same local clock the owner
read them on.

WHAT IT PINS. The two roads that send in the assistant's own voice and then record
what they said: `core.page_hold.release` and `core.notify_flush.flush_pen`.
A page goes in through `state.hold_page`, a pen batch through
`state.enqueue_ping`; what Signal was handed is read off the stand-in for
`shared.signal.send`, and what the assistant remembers is read back through
`outbound.recent_sent`, the block the model reads as its own past messages.
Both must say "16:12 local (CEST)", and neither may still say
"14:12 UTC".

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. On 16 October
2026 local is on summer time, UTC+2 (CEST), so 14:12 UTC is 16:12 CEST.
The sends happen at 12:00 UTC, 14:00 local, outside quiet hours and the
morning gate.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

_AFTERNOON = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
_SAID = "status dashboard down since 14:12 UTC"
_READ = "16:12 local time (CEST)"


@pytest.fixture()
def wire(tmp_path, monkeypatch) -> list[str]:
    """A fresh state file, a page recipient so sends are remembered, the
    clocks open, and a Signal that accepts everything and keeps the body."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.setenv("SIGNAL_RECIPIENT", "+15550100010")
    monkeypatch.setenv("ASSISTANT_QUIET_HOURS", "off")
    from apps.assistant.shared import signal

    bodies: list[str] = []

    def send(subject: str, body: str, *, recipient: str | None = None) -> bool:
        bodies.append(body)
        return True

    monkeypatch.setattr(signal, "send", send)
    return bodies


def _remembered() -> str:
    from apps.assistant.core import outbound

    return outbound.recent_sent()


def test_a_released_page_is_remembered_as_it_was_read(wire) -> None:
    """The held page's UTC time is local in the send and in the memory."""
    from apps.assistant.core import page_hold, state

    state.hold_page(_SAID, road="triage", subject="status dashboard")
    assert page_hold.release(_AFTERNOON) is not None
    assert len(wire) == 1 and _READ in wire[0], wire
    assert _READ in _remembered() and "14:12 UTC" not in _remembered()


def test_a_pen_page_is_remembered_as_it_was_read(wire, monkeypatch) -> None:
    """The pen's composed page, with the model's UTC time, the same way."""
    from apps.assistant.core import notify_flush, state

    monkeypatch.setattr(
        notify_flush,
        "_compose",
        lambda pings, now: notify_flush._Decision(message=_SAID, floor=_SAID),
    )
    state.enqueue_ping("status dashboard down", "probe failed", "notify")
    assert notify_flush.flush_pen(_AFTERNOON) is not None
    assert len(wire) == 1 and _READ in wire[0], wire
    assert _READ in _remembered() and "14:12 UTC" not in _remembered()
