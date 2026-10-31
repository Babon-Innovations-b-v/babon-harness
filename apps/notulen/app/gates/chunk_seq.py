"""Chunk sequence-number gate for POST /api/upload/chunk.

Validation is data where possible: in-order and duplicate chunks return a
verdict string; only protocol violations (gap, bad seq) raise.

FAILURE POLICY: raises ``HTTPException`` 409 on a gap so the browser
re-sends from ``last_seq + 1`` (the iOS-eviction recovery contract); 400 on a non-positive seq. Nothing is swallowed.
"""
from __future__ import annotations

from fastapi import HTTPException


def check_chunk_seq(seq: int, last_seq: int | None) -> str:
    """Classify an incoming chunk's seq number.

    Returns ``"next"`` (write it) or ``"duplicate"`` (ack, no-op:
    sendBeacon may double-fire on pagehide). Raises 409 for out-of-order
    chunks so the browser re-sends from the gap.
    """
    if seq < 1:
        raise HTTPException(status_code=400, detail="Invalid seq (must be >= 1)")
    last = last_seq or 0
    if seq <= last:
        return "duplicate"
    if seq == last + 1:
        return "next"
    raise HTTPException(
        status_code=409,
        detail=f"Out-of-order chunk: expected seq {last + 1}, got {seq}",
    )
