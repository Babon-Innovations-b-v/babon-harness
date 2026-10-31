"""A lifted or lapsed mute is never refiled from the occurrences it already decided.

WHAT IT PINS. `core.recurring_alerts.file_recurring_observations` with the
filed-mute table behind it (`state.record_filed`, `state.clear_filed`): a
subject the filer carded, whose card was then lifted or has lapsed, is filed
again only on occurrences that arrived after that decision, never on the same
fortnight of rows that produced the first card.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The audit rows
are written out by hand: one subject on three separate days before the
decision, and in the last case three more separate days after it. The filer's
own bar is three distinct days, so before the lift the subject qualifies once,
after the lift it has zero new days, and with three new days it qualifies once
more. The issue numbers are the ones the stubbed GitHub hands back, counted.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

_SUBJECT = "systemd unit failed: harness-webhook-self-heal.service"


@pytest.fixture()
def filer(tmp_path, monkeypatch):
    """A fresh state file, hand-written audit rows, and GitHub as a counter.

    Returns (rows, created): append to `rows` to add arrivals; `created` lists
    every issue the filer asked GitHub for.
    """
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "openclaw.db"))
    from apps.assistant.core import recurring_alerts, state

    rows: list[dict] = []
    created: list[dict] = []
    monkeypatch.setattr(state, "alerts_since", lambda _start, limit: list(rows))

    def create(payload: dict, actor: str) -> str:
        created.append(payload)
        return f"created https://github.com/o/r/issues/{len(created)}"

    monkeypatch.setattr(recurring_alerts.github_act, "execute", create)
    return rows, created


def _arrivals_on(rows: list[dict], days_from_now: list[float]) -> None:
    from apps.assistant.core import state

    now = datetime.now(timezone.utc)
    for offset in days_from_now:
        rows.append({
            "name": state.batch_row_name(1, [_SUBJECT]),
            "severity": "warning",
            "received_at": (now + timedelta(days=offset)).isoformat(),
        })


def test_a_lifted_mute_is_not_refiled_from_the_rows_that_filed_it(filer) -> None:
    from apps.assistant.core import recurring_alerts, state

    rows, created = filer
    _arrivals_on(rows, [-4, -3, -2])
    assert [one.number for one in recurring_alerts.file_recurring_observations()] == [1]

    assert state.clear_filed(_SUBJECT) is True
    assert recurring_alerts.file_recurring_observations() == []
    assert len(created) == 1, "the lifted subject was refiled off its old rows"

    _arrivals_on(rows, [0.5, 1.5, 2.5])
    assert [one.number for one in recurring_alerts.file_recurring_observations()] == [2], (
        "three new days after the lift did not file the subject again"
    )


def test_a_lapsed_mute_is_not_refiled_from_the_rows_before_it_lapsed(filer) -> None:
    from apps.assistant.core import recurring_alerts, state

    rows, created = filer
    _arrivals_on(rows, [-4, -3, -2])
    state.record_filed(_SUBJECT, 3, ttl_days=0)

    assert recurring_alerts.file_recurring_observations() == []
    assert created == [], "a lapsed card was refiled off the rows before it lapsed"
