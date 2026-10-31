"""`db` check: connect to a read-only DSN and `SELECT 1`.

`component.target` is the NAME of the env var holding the DSN (not the
DSN itself, DSNs are secrets, they never live in the registry). Unset
env var degrades to `unknown` (creds not wired yet), NOT down, a
missing DSN is a wiring gap, not a dead database. A connect/query error
with the DSN present is `down`.

psycopg2 is imported lazily (module standard §3) so the package imports
without the driver, mirroring `core/tools/infra/db_query.py`. Check-module grammar:
one public `check`.

FAILURE POLICY: connect/query errors return a `down` CheckResult; an
unset DSN returns `unknown`. No raise escapes for those paths; any other
bug propagates to the sweep's per-component Tier-2 catch.
"""
from __future__ import annotations

import os
from typing import Any

from apps.assistant.core.monitor.component import (
    DOWN,
    UNKNOWN,
    UP,
    CheckResult,
    Component,
)
from apps.assistant.core.monitor.limits import CHECK_TIMEOUT_SECONDS


def check(component: Component, prior_row: dict[str, Any] | None = None) -> CheckResult:
    dsn = os.environ.get(component.target, "")
    if not dsn:
        return CheckResult(UNKNOWN, f"{component.target} unset")

    # Lazy driver dep (module standard §3): only an actual probe needs it.
    import psycopg2  # noqa: PLC0415

    connection = None
    try:
        connection = psycopg2.connect(dsn, connect_timeout=CHECK_TIMEOUT_SECONDS)
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return CheckResult(UP, "SELECT 1 ok")
    except psycopg2.Error as exc:
        return CheckResult(DOWN, f"{type(exc).__name__}: {str(exc).strip()}")
    finally:
        if connection is not None:
            connection.close()
