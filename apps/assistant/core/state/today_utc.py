"""UTC day-bucket helper for the state table adapters, declared once.

`budget_day` keys its daily spend counter by this date string; it must
stay consistent with the row timestamps from the `utcnow_iso.py` twin
(one home per duplicated helper; module standard §2: one
public callable per file).

FAILURE POLICY: pure clock read, nothing to fail.
"""
from __future__ import annotations

from datetime import datetime, timezone


def today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")
