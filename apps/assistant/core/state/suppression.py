"""`suppression` table adapter, operator-curated alert-name patterns
we always silence.

Storage-grammar table adapter (blueprint §2.3): match, insert and list
live together. Patterns are SQL LIKE; operators insert wildcards (e.g.
`backup-freshness-%`). See the package overlay for the kubectl-exec
operator workflow.

FAILURE POLICY: Tier-1 fail-loud, suppression read/write errors
propagate. A broken suppression store must fail the webhook rather
than silently page (or silently suppress) the wrong alerts.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from apps.assistant.core.state.conn import get_connection
from apps.assistant.core.state.utcnow_iso import utcnow_iso

log = logging.getLogger("openclaw.suppression")


def is_suppressed(name: str) -> tuple[bool, str | None]:
    """Return (suppressed, reason). Patterns are matched via SQL LIKE
    against the alert name. Operator inserts wildcards (e.g.
    `backup-freshness-%`).
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT pattern, reason FROM suppression WHERE ? LIKE pattern LIMIT 1",
            (name,),
        ).fetchone()
    if row is None:
        return False, None
    return True, row["reason"]


def add_suppression(
    pattern: str, reason: str, added_by: str = "operator", force: bool = False
) -> None:
    """Mute every alert whose name matches this SQL LIKE pattern.

    Refuses a pattern that would also mute something which has paged CRITICAL
    in the last fortnight, unless `force` says the person means it.

    An alertname is a rule group, not an incident. `ResourceHigh` is five
    Prometheus rules under one name, from an info-level load observation up to
    the critical disk-full page, and this table matches on the name. So
    the obvious thing to type after a noisy week is the thing that silences the
    page you most need: a full filesystem, which can leave the assistant
    mute, is watched by one of the five. `recurring_alerts` already refuses to FILE an Alertmanager subject
    for this reason and says so at length; nothing stopped a person muting one
    by hand, which is the same mistake by the other door.

    The check is evidence, not a rule table: it asks what this pattern has
    actually matched at critical in the window, so it needs no copy of the
    Prometheus rules and cannot drift from them. A pattern matching nothing at
    critical is allowed, quietly, which is the ordinary case.

    Raises `CriticalUnderPattern`, carrying the names, so a caller can show the
    person what they were about to lose and let them pass `force=True`.
    """
    if not force:
        blocked = _critical_matches(pattern)
        if blocked:
            raise CriticalUnderPattern(pattern, blocked)
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO suppression (pattern, reason, added_at, added_by) "
            "VALUES (?, ?, ?, ?)",
            (pattern, reason, utcnow_iso(), added_by),
        )
        conn.commit()


class CriticalUnderPattern(Exception):
    """This mute would also cover something that has paged critical."""

    def __init__(self, pattern: str, names: list[str]) -> None:
        self.pattern = pattern
        self.names = names
        super().__init__(
            f"{pattern!r} also matches {len(names)} alert(s) that paged "
            f"critical in the last {_CRITICAL_WINDOW_DAYS} days: "
            + ", ".join(names[:5])
            + ". An alertname is a rule group, so muting it mutes those too. "
            "Narrow the pattern, or pass force=True if you mean it."
        )


#: How far back "has paged critical" looks. A fortnight, the same window
#: `recurring_alerts` uses to decide what keeps coming back.
_CRITICAL_WINDOW_DAYS = 14


def _critical_matches(pattern: str) -> list[str]:
    """Distinct alert names this pattern matches that arrived critical.

    Tier-2 on purpose, and the only catch in this module: a read that fails is
    no evidence of danger, and a mute a person asked for must not be blocked by
    a broken query. It logs and allows.
    """
    since = (
        datetime.now(timezone.utc) - timedelta(days=_CRITICAL_WINDOW_DAYS)
    ).isoformat()
    try:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT DISTINCT name FROM alerts WHERE severity = 'critical' "
                "AND received_at >= ? AND name LIKE ? ORDER BY name",
                (since, pattern),
            ).fetchall()
    except Exception as exc:  # noqa: BLE001 - Tier-2: no evidence is not danger
        log.warning("could not check %r for critical matches: %s", pattern, exc)
        return []
    return [str(row["name"]) for row in rows]


def list_suppressions() -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM suppression ORDER BY added_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]
