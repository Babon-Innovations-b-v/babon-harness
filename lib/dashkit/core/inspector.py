"""Health-check runner harness.

Each dashboard registers a list of ``HealthCheck`` objects (name,
description, SQL query, optional params, healthy_when_zero flag) and
the runner executes them with consistent error handling, returning a
dashboard-friendly payload.

Any dashkit dashboard ships its own checks list and reuses this runner.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(frozen=True)
class HealthCheck:
    name: str
    description: str
    query: str
    params: tuple = field(default_factory=tuple)
    healthy_when_zero: bool = True


def run_checks(conn, checks: Iterable[HealthCheck]) -> list[dict[str, Any]]:
    """Run every check against ``conn`` and return the result list.

    Failures (SQL errors, etc.) are reported as ``healthy=False`` with
    a truncated ``error`` field rather than raised, so a single broken
    check doesn't take down the whole Inspector panel.
    """
    results: list[dict[str, Any]] = []
    for check in checks:
        try:
            with conn.cursor() as cur:
                cur.execute(check.query, check.params)
                row = cur.fetchone()
                count = row[0] if row else 0
            results.append({
                "name": check.name,
                "description": check.description,
                "count": int(count or 0),
                "healthy": (count == 0)
                if check.healthy_when_zero
                else (count > 0),
            })
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                # Defended swallow: rollback is cleanup after the check
                # already failed; a dead connection here changes
                # nothing; the check is reported unhealthy below either
                # way.
                pass
            results.append({
                "name": check.name,
                "description": check.description,
                "count": None,
                "healthy": False,
                "error": str(exc)[:200],
            })
    return results
