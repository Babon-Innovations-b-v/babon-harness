"""A page that page_hold dropped never reads as sent in the current picture.

WHAT IT PINS. `core.awareness.render`, the block every model loop reads its
recent alerts from, across its public interface, with the tables seeded through
`state.hold_page`, `state.record_alert` and `state.mark_dropped` in the order
`gates/app` and `core/page_hold` write them. An arrival row whose decision was a
page says what became of that page: held, sent, dropped with its reason, or
never queued.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Each case is
one arrival on its own fingerprint, and what happened to its page is written
by the fixture itself: dropped with an already-paged reason, left waiting, or
never held.
"""
from __future__ import annotations

import pytest

_DROPPED = "ce1ac10765267c1e"
_WAITING = "9c620cfb66dd863e"
_NEVER_HELD = "5150d716aa00bb11"
_REASON = "this firing was already paged at 2000-01-01T12:00:00"


@pytest.fixture()
def picture(tmp_path, monkeypatch) -> str:
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    from apps.assistant.core import awareness, state

    for fingerprint in (_DROPPED, _WAITING, _NEVER_HELD):
        if fingerprint != _NEVER_HELD:
            held = state.hold_page(
                "TargetDown: tls-watchdog dark.", road="alertmanager",
                subject="TargetDown", severity="warning", key=fingerprint,
            )
            if fingerprint == _DROPPED:
                state.mark_dropped([held], reason=_REASON)
        state.record_alert(
            fingerprint=fingerprint, name="TargetDown", severity="warning",
            status="firing", decision="enrich", reason="fixture",
            signal_sent=False, dead_letter=False,
        )
    return awareness.render()


def _line(picture: str, fingerprint: str) -> str:
    return next(line for line in picture.splitlines() if f"[{fingerprint}]" in line)


def test_a_dropped_page_says_it_was_never_sent_and_why(picture) -> None:
    line = _line(picture, _DROPPED)
    assert "dropped, never sent" in line
    assert _REASON in line


def test_a_waiting_page_says_it_has_not_gone_yet(picture) -> None:
    assert "held, not sent yet" in _line(picture, _WAITING)


def test_a_page_that_was_never_queued_says_not_delivered(picture) -> None:
    assert _line(picture, _NEVER_HELD).endswith("(not delivered)")
