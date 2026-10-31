"""`component_status` table adapter, the live liveness row per stack
component.

Storage-grammar table adapter (blueprint §2.3): the component-status
read + write callables live together in the file named after the table.
One row per registry component, keyed by its `name`; the sweep
(`core.monitor.sweep`) is the only writer for poll-checked components and
the `/webhook/heartbeat` gate is the only writer for push components.

The row carries the raw liveness facts, `status`, `last_ok_at`,
`last_checked_at`, `consecutive_fails`, `detail`. The down-threshold
POLICY (how many consecutive misses count as down) lives in the sweep,
not here: this adapter persists whatever status the sweep computed. That
keeps the table a dumb store and the flap-suppression logic in one place.

FAILURE POLICY: Tier-1 fail-loud, like every other `core.state`
adapter, read/write errors propagate. A status write that silently
failed would make the monitor lie about the stack; the sweep's own
Tier-2 page guard is layered ON TOP of these loud writes, never instead
of them.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from apps.assistant.core.state.conn import get_connection
from apps.assistant.core.state.utcnow_iso import utcnow_iso

log = logging.getLogger("openclaw.state.component_status")

# Status vocabulary. `pending` is the implicit pre-first-check state (a
# component with no row yet); the three real states are set by the sweep.
STATUS_UP = "up"
STATUS_DOWN = "down"
STATUS_UNKNOWN = "unknown"
STATUS_PENDING = "pending"


def record_check(
    component: str,
    status: str,
    ok: bool,
    detail: str,
    consecutive_fails: int,
    stamp_last_ok: bool = True,
) -> None:
    """Persist the outcome of one poll check for `component`.

    The sweep computes `status` + `consecutive_fails` (it owns the
    down-threshold policy) and hands them here to store. `ok` stamps
    `last_ok_at` so a recovered component records when it last passed,
    independent of the current status string.

    `stamp_last_ok=False` records the check WITHOUT touching `last_ok_at`.
    That is what a push-only component needs; without it a push-only watch
    is structurally unable to fail. A heartbeat component proves
    it is alive by POSTing `/webhook/heartbeat`; its check does nothing but
    read `last_ok_at` back. With the sweep stamping that same field on every
    pass, the check would read its own previous answer, so a heartbeat that
    had been seen once would stay `up` forever no matter what its
    sender did. Only the sender may write that field.
    """
    now = utcnow_iso()
    last_ok = now if (ok and stamp_last_ok) else None
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO component_status "
            "(component, status, last_ok_at, last_checked_at, consecutive_fails, detail) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(component) DO UPDATE SET "
            "status = excluded.status, "
            "last_checked_at = excluded.last_checked_at, "
            "consecutive_fails = excluded.consecutive_fails, "
            "detail = excluded.detail, "
            "last_ok_at = COALESCE(excluded.last_ok_at, component_status.last_ok_at)",
            (component, status, last_ok, now, consecutive_fails, detail),
        )
        conn.commit()


def record_heartbeat(component: str) -> None:
    """Record a push heartbeat for a `heartbeat`-kind component.

    A heartbeat is proof-of-life: it stamps `last_ok_at` +
    `last_checked_at` to now and clears the fail counter. It deliberately
    does NOT flip status to up, the sweep owns status (it decides up vs
    down by comparing `last_ok_at` against the component's max-staleness),
    so a heartbeat only refreshes the timestamp the sweep reads.
    """
    now = utcnow_iso()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO component_status "
            "(component, status, last_ok_at, last_checked_at, consecutive_fails, detail) "
            "VALUES (?, ?, ?, ?, 0, ?) "
            "ON CONFLICT(component) DO UPDATE SET "
            "last_ok_at = excluded.last_ok_at, "
            "consecutive_fails = 0",
            (component, STATUS_PENDING, now, now, "heartbeat received"),
        )
        conn.commit()


def get_one(component: str) -> dict[str, Any] | None:
    """Return the current row for `component`, or None if never checked."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM component_status WHERE component = ?",
            (component,),
        ).fetchone()
    return dict(row) if row is not None else None


def get_all() -> list[dict[str, Any]]:
    """Return every component's current status row, name-ordered.

    Rows for components nobody sweeps any more are included; this module has no
    opinion about which names are current, and the registry is not importable
    from here without turning a state table into a consumer of the thing that
    fills it. `forget_all_but` is how the sweep keeps the table honest.
    """
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM component_status ORDER BY component"
        ).fetchall()
    return [dict(row) for row in rows]


def forget_all_but(components: Iterable[str]) -> int:
    """Drop rows for components that are no longer swept. Returns how many.

    Deleting from the registry and pruning here belong together. A removed
    component would otherwise keep its row forever: `get_all` has no WHERE
    clause and `stack_status` renders every row it returns, so components that
    stopped being checked would go on being reported from readings frozen on
    the day they were cut, UP or NOT UP.

    The sweep's own staleness line cannot catch it either: it takes the newest
    stamp across the table, and the components still being swept keep that
    fresh no matter how old the orphans are.

    Called from the sweep because the sweep is the thing that knows what the
    stack is this minute. A row is deleted rather than flagged: an unswept
    component has no status, and "unknown" already means something else here.
    """
    names = tuple(components)
    if not names:
        # An empty registry is a bug upstream, not an instruction to wipe the
        # table. Refusing to act on it costs one stale sweep; obeying it would
        # cost every status the container knows.
        log.error("forget_all_but called with no components; refusing to prune")
        return 0
    placeholders = ",".join("?" * len(names))
    with get_connection() as conn:
        cursor = conn.execute(
            f"DELETE FROM component_status WHERE component NOT IN ({placeholders})",
            names,
        )
        return cursor.rowcount or 0
