"""Daily Anthropic spend cap, the budget policy seam.

Policy over the durable `core.state.budget_day` counter:
a pod restart no longer zeroes spend, so a CrashLoop can't reset the
counter and burn the daily cap. One public callable per file:

    cap.py         cap_eur(), the configured daily cap (env-tunable)
    is_tripped.py  is_tripped(), hard gate the LLM loops check first
    charge.py      charge(cost_eur), record one LLM call's cost
    snapshot.py    snapshot(), operator view (see overlay workflow)

Cap default is €5/day, env-tunable via `OPENCLAW_DAILY_CAP_EUR`. Set
to `0` in tests to verify the tripped path without paying for an LLM
call.

FAILURE POLICY: Tier-1 fail-loud, reads and writes go through the
`core.state` seam and propagate. A budget store that cannot answer
must fail the triage call (which then pages raw) rather than guess.
"""
from __future__ import annotations

from apps.assistant.shared.budget.cap import cap_eur
from apps.assistant.shared.budget.charge import charge
from apps.assistant.shared.budget.is_tripped import is_tripped
from apps.assistant.shared.budget.snapshot import snapshot

__all__ = ["cap_eur", "charge", "is_tripped", "snapshot"]
