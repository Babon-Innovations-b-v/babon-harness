"""Operator view of today's spend vs cap (kubectl-exec workflow in the
package overlay).

FAILURE POLICY: Tier-1, store/env errors propagate.
"""
from __future__ import annotations

from apps.assistant.core import state as _state
from apps.assistant.shared.budget.cap import cap_eur


def snapshot() -> dict[str, float | str]:
    return {
        "spend_eur": round(_state.budget_spend_today_eur(), 6),
        "cap_eur": cap_eur(),
    }
