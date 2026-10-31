"""The configured daily Anthropic spend cap in euros.

Env read at call time (`OPENCLAW_DAILY_CAP_EUR`), default €5/day.

FAILURE POLICY: Tier-1, a malformed env value raises `ValueError`
loudly rather than silently falling back to the default.
"""
from __future__ import annotations

import os

_DEFAULT_CAP_EUR = 5.0


def cap_eur() -> float:
    raw = os.environ.get("OPENCLAW_DAILY_CAP_EUR")
    if raw is None or raw == "":
        return _DEFAULT_CAP_EUR
    return float(raw)
