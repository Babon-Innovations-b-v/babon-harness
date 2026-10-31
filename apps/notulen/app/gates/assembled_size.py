"""Assembled-recording size gate for POST /api/upload/finalize.

Only a lower bound. There is no upper bound: a long meeting is exactly the
recording we least want to refuse.

FAILURE POLICY: raises ``HTTPException`` (400) with user copy;
nothing is swallowed. Without the lower bound we would dispatch a GPU job
that transcribes silence.
"""
from __future__ import annotations

from fastapi import HTTPException

MIN_ASSEMBLED_BYTES = 10_000


def check_assembled_size(num_bytes: int) -> None:
    """Reject assembled tempfiles that are obviously empty."""
    if num_bytes < MIN_ASSEMBLED_BYTES:
        raise HTTPException(
            status_code=400,
            detail="No recording received (too small to process)",
        )
