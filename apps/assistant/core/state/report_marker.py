"""`report_marker` table adapter, where each report left off.

A grounded report diffs the world since the LAST time that same report ran:
the morning brief against the previous morning. This stores one marker per
report kind (the ISO time it last ran, and the main SHA it last saw), so
`core.changes` can ask "what changed since then". A kind in
`RETIRED_REPORT_KINDS` has no last run: its beat is gone.

No production code reads or writes a marker: every report
kind is retired, and `whats_changed` derives its window from the schedule. What is left is the boot cleanup and the e2e round trip.

FAILURE POLICY: Tier-1 fail-loud, a marker read/write error propagates, like every state adapter. A report that cannot read its marker
must not silently pretend nothing changed.
"""
from __future__ import annotations

from typing import Any

from apps.assistant.core.state.conn import get_connection
from apps.assistant.core.state.utcnow_iso import utcnow_iso

# Report beats that no longer write a marker. A retired beat's marker can stay
# behind in the state DB, and a row nothing can advance again is worse than no
# row: a reader anchoring a diff window on `marked_at` widens that window by a
# day every day. Append a kind here when a report beat is retired.
#
# The morning brief and the weekly advisor are listed because both run as
# gateway automations, which have no marker writer, so their rows would freeze.
# `whats_changed` works its window out from the schedule and reads no marker
# at all; listing both kinds here lets the boot cleanup drop a frozen row.
RETIRED_REPORT_KINDS = frozenset({"evening", "morning", "weekly"})


def get_report_marker(report_kind: str) -> dict[str, Any] | None:
    """The last (marked_at, sha) for this report kind, or None if it has never
    run or its beat was retired (the caller then falls back to a default
    window)."""
    kind = report_kind.strip().lower()
    if kind in RETIRED_REPORT_KINDS:
        return None
    with get_connection() as conn:
        row = conn.execute(
            "SELECT report_kind, marked_at, sha FROM report_marker WHERE report_kind = ?",
            (kind,),
        ).fetchone()
    return dict(row) if row else None


def set_report_marker(report_kind: str, sha: str, marked_at: str | None = None) -> None:
    """Record that `report_kind` just reported, at `marked_at` (default now)
    and up to main `sha`. Upsert: one row per kind."""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO report_marker (report_kind, marked_at, sha) VALUES (?, ?, ?) "
            "ON CONFLICT(report_kind) DO UPDATE SET marked_at = excluded.marked_at, sha = excluded.sha",
            (report_kind.strip().lower(), marked_at or utcnow_iso(), sha.strip()),
        )
        conn.commit()


def drop_retired_markers() -> int:
    """Delete the markers of retired beats, returning how many rows went.

    Housekeeping in the shape of `dedup_window.vacuum_old_dedup_rows`: cheap,
    idempotent, run at pod boot. Retiring a beat reaches the route, the timer and the
    writer but not the state DB, so without this its row would outlive the
    beat forever.
    """
    kinds = sorted(RETIRED_REPORT_KINDS)
    if not kinds:
        return 0
    placeholders = ", ".join("?" for kind in kinds)
    with get_connection() as conn:
        cursor = conn.execute(
            f"DELETE FROM report_marker WHERE report_kind IN ({placeholders})",
            kinds,
        )
        conn.commit()
        return cursor.rowcount or 0
