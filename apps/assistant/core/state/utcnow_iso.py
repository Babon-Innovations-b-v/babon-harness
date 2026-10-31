"""UTC timestamp helper for the state table adapters, declared once.

Every row-stamping adapter (`alerts`, `chat_turns`, `dedup_window`,
`suppression`) imports this clock so timestamps compare byte-stably
across tables (one home per duplicated helper; module standard §2,
one public callable per file). The day-bucket twin lives in
`today_utc.py`.

FAILURE POLICY: pure clock read, nothing to fail.
"""
from __future__ import annotations

from datetime import datetime, timezone


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
