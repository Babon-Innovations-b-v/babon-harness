"""`my_actions` lists a page held overnight with its local time, and the dropped ones too.

WHAT IT PINS. `my_actions.execute`, the door read the weekday brief takes the
night from: a page still waiting shows its subject and the minute it
arrived on the local clock, and a page held since the last brief that was
dropped as no longer news shows with its reason, so the brief can say an
outage ended overnight instead of saying nothing.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The pages are
held at 23:42 UTC and 01:10 UTC on 15/16 October 2026, times chosen by hand
and not computed by the code; local is on summer time (UTC+2) until 25
October, so they arrived at Fri 01:42 and Fri 03:10 local, written out by
hand. The fixed clock puts the brief at Friday 08:05, so the window opens at
Thursday's 08:00 and both pages are inside it.
"""
from __future__ import annotations

from apps.assistant.shared.name import ASSISTANT_NAME

from datetime import datetime, timezone

import pytest

from apps.assistant.core import state
from apps.assistant.core.tools.meta import my_actions

_BRIEF_RUNS = datetime(2026, 10, 16, 6, 5, tzinfo=timezone.utc)


@pytest.fixture()
def night(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """One page still held and one dropped because its alert resolved."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    state.reset_for_tests()

    class _FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: D102 - the brief's own minute
            return _BRIEF_RUNS if tz is None else _BRIEF_RUNS.astimezone(tz)

    monkeypatch.setattr(my_actions, "datetime", _FixedClock)
    state.hold_page(
        "TargetDown: signal-bridge metrics gone dark.", road="alertmanager",
        subject="TargetDown", severity="warning", now="2026-10-15T23:42:00+00:00",
    )
    dropped = state.hold_page(
        "assistant-whisper container is down.", road="alertmanager",
        subject=f"AssistantWhisperDown", severity="warning", now="2026-10-16T01:10:00+00:00",
    )
    state.mark_dropped([dropped], reason="its alert resolved at 01:20")


def test_the_held_page_carries_its_local_arrival(night) -> None:
    answer = my_actions.execute({})

    assert "[Fri 01:42 local] held to send -> TargetDown" in answer, answer


def test_a_page_dropped_overnight_is_listed_with_why(night) -> None:
    answer = my_actions.execute({})

    assert (
        f"[Fri 03:10 local] held, then not sent -> AssistantWhisperDown: "
        "its alert resolved at 01:20"
    ) in answer, answer
