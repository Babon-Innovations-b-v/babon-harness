"""Single-chunk size gate for POST /api/upload/chunk.

FAILURE POLICY: raises ``HTTPException`` (400/413); nothing is swallowed.
"""
from __future__ import annotations

from fastapi import HTTPException

MAX_CHUNK_BYTES = 10_000_000  # 10 MB per chunk (a 5-sec opus chunk is ~30 KB)


def check_chunk_size(num_bytes: int) -> None:
    """Reject obviously empty or oversize single chunks."""
    if num_bytes <= 0:
        raise HTTPException(status_code=400, detail="Empty chunk")
    if num_bytes > MAX_CHUNK_BYTES:
        raise HTTPException(status_code=413, detail="Chunk too large (max 10MB)")
