"""`pod_boots` table adapter: one row per pod start, so a restart leaves a
trace that outlives the cluster's own memory.

Kubernetes keeps no restart history a week later. ReplicaSets roll off at
`revisionHistoryLimit` (10, and a busy day can roll more than that),
namespace Events expire
after about an hour, and a Prometheus outside the cluster may carry no
kube-state-metrics series at all, so a 30-day range query for
`kube_pod_container_status_restarts_total` can come back empty. openclaw's own
sweep cannot prove it either: at `SWEEP_INTERVAL_SECONDS` 60 and
`DOWN_THRESHOLD` 3 a restart under ~3 minutes never flips the status, and
`component_status` holds one row per component that is overwritten in
place, so nothing accumulates. "Did the container flap last week" therefore had
no answer after the fact; the deadman flag and the forward watchdog bound
such an outage while it is happening, neither one records that it did.

The volume-backed SQLite is the one store that already survives every
restart (its `budget_day` rows survive
every rollout), so the container writes its own start
here and the history is kept where it survives.

Storage-grammar adapter (blueprint §2.3): the read + write callables live
together in the file named after the table. Append-only.

FAILURE POLICY: Tier-1 fail-loud like every state adapter. A boot that
cannot be recorded is a hole in exactly the history this table exists to
keep, and a pod that cannot write its own state volume must crash rather than limp
(see `conn.py`).
"""
from __future__ import annotations

from typing import Any

from apps.assistant.core.state.conn import get_connection
from apps.assistant.core.state.utcnow_iso import utcnow_iso


def record_boot(pod: str) -> int:
    """Record that the container process started just now. `pod` is the container name
    (`HOSTNAME` in the cluster), which is what separates a container
    restart in place from a replacement pod. Returns the row id."""
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO pod_boots (pod, booted_at) VALUES (?, ?)",
            (pod[:120], utcnow_iso()),
        )
        conn.commit()
        return int(cur.lastrowid)


def starts_between(iso_start: str, iso_end: str) -> list[dict[str, Any]]:
    """Every start in `[iso_start, iso_end)`, oldest first, each carrying
    `in_place`: 1 when the same pod name booted before (a container restart
    in place, the thing that counts as a crash), 0 for a pod's first start
    (a rollout or a reschedule). Checked against the whole history, so a pod
    first seen before the window still makes its later starts in place."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, pod, booted_at, EXISTS ("
            "  SELECT 1 FROM pod_boots AS earlier WHERE earlier.pod = pod_boots.pod"
            "  AND (earlier.booted_at < pod_boots.booted_at"
            "       OR (earlier.booted_at = pod_boots.booted_at AND earlier.id < pod_boots.id))"
            ") AS in_place FROM pod_boots WHERE booted_at >= ? AND booted_at < ? "
            "ORDER BY booted_at ASC",
            (iso_start, iso_end),
        ).fetchall()
    return [dict(row) for row in rows]


def first_boot_at() -> str | None:
    """When the history itself begins, or None while nothing is recorded.

    Without it a quiet window is unreadable: no rows since Monday means
    "it did not restart" only if the table was already recording on
    Monday. Absent evidence is never good news."""
    with get_connection() as conn:
        row = conn.execute("SELECT MIN(booted_at) AS first_at FROM pod_boots").fetchone()
    return row["first_at"] if row and row["first_at"] else None
