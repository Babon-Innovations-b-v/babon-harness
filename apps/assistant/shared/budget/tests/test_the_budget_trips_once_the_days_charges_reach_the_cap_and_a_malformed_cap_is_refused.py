"""The budget trips once the day's charges reach the cap, and a malformed cap is refused.

WHAT IT PINS. `shared.budget`, the gate both model loops check before any
Anthropic call: `charge` adds one call's cost to today's durable counter,
`is_tripped` is true once that counter has reached `cap_eur()`, `snapshot`
shows both, and a cap that is not a number raises rather than falling back to
the default. The counter lives in a fresh state database on a frozen clock.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The charges are
made-up euro amounts summed by hand against the made-up cap: 0.75 + 0.25 is
exactly 1.00, which has reached a cap of 1.00; the default cap is the stated
5.00 euros a day.

ONE FUNCTION. This module's one test. A new check is a parametrized case of
it, never a second function.

WHAT IT WAS PROVED AGAINST. The break in this test's register row trips only
past the cap, so the case that lands exactly on it is not tripped.

GUARDS. One test per module (#1210), 2026-11-05.
"""
from __future__ import annotations

import pytest

from apps.assistant.core import state
from apps.assistant.shared import budget

CASES = [
    pytest.param("1.00", (0.40,), (False, {"spend_eur": 0.4, "cap_eur": 1.0}), id="under-the-cap"),
    pytest.param("1.00", (0.75, 0.25), (True, {"spend_eur": 1.0, "cap_eur": 1.0}), id="exactly-on-the-cap"),
    pytest.param("", (4.99,), (False, {"spend_eur": 4.99, "cap_eur": 5.0}), id="the-default-cap"),
    pytest.param("0", (), (True, {"spend_eur": 0.0, "cap_eur": 0.0}), id="a-zero-cap-trips-before-any-call"),
    pytest.param("five euros", (), "ValueError", id="a-malformed-cap-is-refused"),
]


@pytest.mark.parametrize("cap, charges, expected", CASES)
def test_the_budget_trips_once_the_days_charges_reach_the_cap_and_a_malformed_cap_is_refused(
        cap: str, charges: tuple, expected: object, monkeypatch: pytest.MonkeyPatch, tmp_path, frozen_clock) -> None:
    """(tripped, snapshot) after the day's charges is the hand-summed answer."""
    monkeypatch.setenv("OPENCLAW_STATE_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("OPENCLAW_DAILY_CAP_EUR", cap)
    state.reset_for_tests()
    for cost in charges:
        budget.charge(cost)
    try:
        seen: object = (budget.is_tripped(), budget.snapshot())
    except ValueError as refusal:
        seen = type(refusal).__name__
    assert seen == expected
