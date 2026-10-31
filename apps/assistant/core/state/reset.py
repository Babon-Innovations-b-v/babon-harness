"""Test hook: drop the cached SQLite connections so tests can swap DB
paths via `OPENCLAW_STATE_PATH` between cases.

FAILURE POLICY: Tier-1, close errors propagate (only tests call this).
"""
from __future__ import annotations

from apps.assistant.core.state import conn


def reset_for_tests() -> None:
    """Drop the process-local connection cache so tests can swap paths
    via `OPENCLAW_STATE_PATH`."""
    conn._close_all()
