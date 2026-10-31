"""The budget hard gate: has today's spend reached the daily cap?

Checked by both LLM loops (`core.triage`, `core.chat`) BEFORE any
Anthropic call, tripped means no call is made at all.

FAILURE POLICY: Tier-1, store/env errors propagate (see package
docstring).
"""
from __future__ import annotations

from apps.assistant.core import state as _state
from apps.assistant.shared.budget.cap import cap_eur


def is_tripped() -> bool:
    return _state.budget_spend_today_eur() >= cap_eur()
