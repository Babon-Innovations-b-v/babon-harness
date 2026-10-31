"""A standing fault paged long ago is paged again when triage drafts a new page.

WHAT IT PINS. `core.page_hold.release`, the wire in front of the phone, across
its public interface: pages go in through `state.hold_page`, arrivals through
`state.record_alert` in the order `gates/app` writes them, and what comes back
is the text that reached the phone. Inside one firing episode a second page is
dropped only while the last delivery on its fingerprint is younger than the
window the triage prompt tells the model about; after that it is news again.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. One fingerprint
that fires and never resolves, written out by hand: a first page that lands, a
second draft an hour before the window ends (so Alertmanager's four-hourly
re-send folds away), and a third draft an hour after it (so it goes). The
window is read out of the sentence `core.triage` puts in front of the model,
not from the constant, so a prompt and a mechanism that disagree fail here.
Whether a page landed is read off the list standing in for the phone.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest

_KEY = "9c620cfb66dd863e"
_PAGE = "Alert delivery drill still overdue."


@pytest.fixture()
def phone(tmp_path, monkeypatch) -> list[str]:
    """A fresh queue with the clocks open and a list standing in for the
    phone. Only the Signal send is replaced."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    monkeypatch.setenv("ASSISTANT_QUIET_HOURS", "off")
    from apps.assistant.core import page_hold

    landed: list[str] = []
    monkeypatch.setattr(
        page_hold._signal_dispatch,
        "send",
        lambda subject, body: landed.append(body) or True,
    )
    return landed


def _page(text: str) -> None:
    """One triage draft as `gates/app` writes it: held, then its arrival."""
    from apps.assistant.core import state

    state.hold_page(text, road="alertmanager", subject="TargetDown",
                    severity="warning", key=_KEY)
    state.record_alert(
        fingerprint=_KEY, name="TargetDown", severity="warning",
        status="firing", decision="enrich", reason="fixture",
        signal_sent=False, dead_letter=False,
    )


def _release(hours_later: float) -> str | None:
    from apps.assistant.core import page_hold

    return page_hold.release(datetime.now(timezone.utc) + timedelta(hours=hours_later))


def _window_the_model_is_told() -> float:
    """The hours the triage prompt says a still-firing page stays dropped."""
    from apps.assistant.core import triage

    told = re.search(
        r"already paged in\s+the last (\d+) hours is dropped", triage._SYSTEM_PROMPT
    )
    assert told, "the triage prompt no longer states the re-page window"
    return float(told.group(1))


def test_a_repage_inside_the_window_folds_and_one_after_it_goes(phone) -> None:
    """Delivered, re-drafted inside the window (dropped), then after it (sent)."""
    window = _window_the_model_is_told()
    _page(_PAGE)
    assert _release(0) is not None and len(phone) == 1, "the first page never left"

    _page(_PAGE + " Re-sent by Alertmanager.")
    assert _release(window - 1) is None and len(phone) == 1, (
        "a re-send inside the window the model is told reached the phone again"
    )

    _page(_PAGE + " 57 days now, limit 40.")
    assert _release(window + 1) is not None and len(phone) == 2, (
        "a fault still firing past the window the model is told was never paged again"
    )
