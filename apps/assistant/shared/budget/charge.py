"""Record one LLM call's cost against today's durable counter.

FAILURE POLICY: Tier-1, a failed write propagates; silently dropping
a charge would let spend run past the cap (see package docstring).
"""
from __future__ import annotations

from apps.assistant.core import state as _state


def charge(cost_eur: float) -> None:
    _state.budget_charge(cost_eur)
