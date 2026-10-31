"""Daily Job cost ceiling, read at CALL time.

FAILURE POLICY: pure env read. A malformed ``MAX_DAILY_JOBS`` raises
ValueError at the call site, because a silently applied default would
disable the cost ceiling.
"""

from __future__ import annotations

import os


def max_daily_jobs() -> int:
    """Cost circuit breaker: max notulen Jobs created in a rolling 24 h."""
    return int(os.environ.get("MAX_DAILY_JOBS", "50"))
