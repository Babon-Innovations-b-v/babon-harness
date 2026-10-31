"""Deduper: the relay's in-process (fingerprint, status) gate, 30-minute window.

Alertmanager re-posts a firing group roughly every 30 seconds; this keeps one
outage to one message per half hour while the relay is the road to the phone.
Keyed on status as well, so "it stopped" is never muted by the "it started"
before it. State is per process: a restart errs toward repeating a message,
never toward silence.
"""
from __future__ import annotations

import time
from collections import OrderedDict

DEDUPE_WINDOW_S = 1800


class Deduper:
    """In-process LRU keyed by `(fingerprint, status)` with a TTL."""

    def __init__(self, ttl_s: int = DEDUPE_WINDOW_S, max_entries: int = 4096) -> None:
        self._ttl = ttl_s
        self._max = max_entries
        self._seen: OrderedDict[tuple[str, str], float] = OrderedDict()

    def _purge_expired(self, now: float) -> None:
        cutoff = now - self._ttl
        while self._seen:
            key, seen_at = next(iter(self._seen.items()))
            if seen_at >= cutoff:
                return
            self._seen.popitem(last=False)

    def should_send(self, fingerprint: str, status: str, *, now: float | None = None) -> bool:
        """Return True if `(fingerprint, status)` has not been seen within TTL."""
        if now is None:
            now = time.time()
        self._purge_expired(now)
        key = (fingerprint, status)
        if key in self._seen:
            self._seen.move_to_end(key)
            return False
        self._seen[key] = now
        if len(self._seen) > self._max:
            self._seen.popitem(last=False)
        return True
