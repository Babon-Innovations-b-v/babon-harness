"""`page_hold` table, the queue every finished page waits in.

The assistant had two roads that reach a phone from machine events and they did not
know about each other. The notify pen collected pings, held them overnight and
composed one page; the Alertmanager road ran triage and sent its own draft the
moment it had one. The two could send seconds apart, and the second road could
put message after message on a phone between 22:00 and 07:30, because only the
first had brakes.

This table is where they meet. A page is not a page until it has been through
one clock, so both composers finish by writing a row here, and one release pass
decides when anything leaves.

WHY A SECOND QUEUE RATHER THAN THE PEN. The pen holds INPUT: unread pings that
cost nothing to keep and are composed once, at 07:30, over the whole night. What
triage holds is OUTPUT, already written, because its evidence was only fresh in
the night and it cannot be re-derived in the morning. Those are different things and
putting a finished page into `notify_pen` would corrupt what that table means:
`seen_count` counts pings and renders "Ping 5 on this subject", and
`_split_silenced`, `ping_facts.bundle` and the `pen flush (N pings)` audit
grammar would all have to branch on a row that must never be parsed.

Public callables: `hold(...)`, `pending(...)`, `mark_released(...)`,
`oldest_pending_age_seconds()`, `recent_held(...)`, `pending_for_key(...)`,
`add_cover(...)`, `last_released_text(...)`, `held_for_arrival(...)`,
`dropped_since(...)`.

FAILURE POLICY: Tier-1 fail-loud, like every state adapter. A failed read or
write propagates. A page that cannot be queued must not look queued: the caller
still holds it and can fall back, and a swallowed write here would lose a page
silently, which is the failure this whole PRD exists to remove.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from apps.assistant.core.state.conn import get_connection
from apps.assistant.core.state.utcnow_iso import utcnow_iso


def hold(
    text: str,
    *,
    road: str,
    subject: str = "",
    severity: str = "",
    key: str = "",
    covers: str = "",
    worklist_items: str = "",
    now: str | None = None,
) -> int:
    """Queue one finished page and return its row id. Decides nothing.

    `key` is the caller's identity for the thing being reported, an alert
    fingerprint on the triage road and empty on the pen's. `release` keeps only
    the newest row per key, so a road that has lost its own quieting cannot
    stack seven drafts about one fingerprint into one morning message.
    `covers` is a comma-joined list of the other fingerprints the page speaks
    for, one shared cause. `worklist_items` is a comma-joined list of
    the worklist item ids the page is about, empty when its road knew of none.
    """
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO page_hold "
            "(road, subject, text, severity, key, covers, worklist_items, held_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (road, subject, text, severity, key, covers, worklist_items or None, now or utcnow_iso()),
        )
    return int(cursor.lastrowid)


def pending(limit: int = 200) -> list[dict[str, Any]]:
    """Everything still waiting, oldest first.

    Bounded because a release pass reads this on every tick and an unbounded
    read would turn a stuck queue into a slow one as well as a silent one.
    """
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM page_hold WHERE released_at IS NULL "
            "ORDER BY held_at, id LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def pending_count() -> int:
    """How many finished pages are still queued right now.

    A COUNT rather than `len(pending())`, which is bounded at 200 and would
    under-report the exact case worth reporting: a queue that grew past its own
    read cap.

    HELD IS NOT UNHEARD, and this number is what lets the weekly silence report
    say so. The quiet-hours hold and the pacing hold in `core/page_hold.release`
    write nothing to `alerts`, so a page waiting here is invisible to any read
    of that table and would be counted as a subject nobody was told about.
    On a busy night most of the messages that could have reached a phone are
    this number, and every one of them is correctly held.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS waiting FROM page_hold WHERE released_at IS NULL"
        ).fetchone()
    return int(row[0] or 0) if row else 0


def mark_released(ids: list[int], *, now: str | None = None) -> None:
    """Stamp the rows that just went out.

    Only what actually fitted in the message is stamped; the rest stays pending
    and rides the next pass, which is the difference between this and the old
    `_join_drafts` trailer that said "(+N more not shown)" and dropped them.
    """
    if not ids:
        return
    marks = ",".join("?" for _ in ids)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE page_hold SET released_at = ? WHERE id IN ({marks})",
            (now or utcnow_iso(), *ids),
        )


def mark_dropped(ids: list[int], *, reason: str, now: str | None = None) -> None:
    """Take rows out of the queue that will never be sent, saying why.

    They leave `pending` like a released row does, and the reason is kept so
    the table still reads as the audit of what was held and what became of
    it. `last_release_at` skips them: nothing went out.
    """
    if not ids:
        return
    marks = ",".join("?" for _ in ids)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE page_hold SET released_at = ?, dropped_because = ? "
            f"WHERE id IN ({marks})",
            (now or utcnow_iso(), reason, *ids),
        )
        conn.commit()


def last_release_at() -> str | None:
    """When a page last left, or None when none ever has.

    This is the pacing clock, and it reads what WENT OUT rather than what was
    queued. Reading flush stamps instead would make every silence look like a
    page that had just gone, and most flushes are silences, so the pacing
    would sit in a story gap of its own making.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT MAX(released_at) FROM page_hold WHERE dropped_because IS NULL"
        ).fetchone()
    return row[0] if row and row[0] else None


def oldest_pending_age_seconds(now: datetime | None = None) -> float:
    """How long the oldest waiting page has waited, 0.0 when nothing waits.

    Exported as a metric so the VM-side deadman can page on a stuck queue
    DIRECT. That routing is the point: once both roads run through one release
    pass, a release that stops is a single total failure rather than two
    partial ones, and it cannot report itself through the queue it is stuck in.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT MIN(held_at) FROM page_hold WHERE released_at IS NULL"
        ).fetchone()
    if not row or not row[0]:
        return 0.0
    moment = datetime.fromisoformat(row[0])
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return max(0.0, ((now or datetime.now(timezone.utc)) - moment).total_seconds())


def pending_for_key(key: str) -> dict[str, Any] | None:
    """The newest page still waiting under `key`, or None."""
    if not key:
        return None
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM page_hold WHERE released_at IS NULL AND key = ? "
            "ORDER BY held_at DESC, id DESC LIMIT 1",
            (key,),
        ).fetchone()
    return dict(row) if row else None


def add_cover(row_id: int, fingerprint: str) -> None:
    """Add one fingerprint to the ones a held page speaks for.

    Triage writes it when a silence names a queued page as its cover, so the
    release that sends the page stamps the silenced fingerprint delivered too.
    """
    with get_connection() as conn:
        conn.execute(
            "UPDATE page_hold SET covers = "
            "CASE WHEN COALESCE(covers, '') = '' THEN ? ELSE covers || ',' || ? END "
            "WHERE id = ?",
            (fingerprint, fingerprint, row_id),
        )
        conn.commit()


#: How long before its audit row an arrival's page can have been held. The gate
#: holds every page of an envelope, then audits every arrival, so it is
#: milliseconds in practice.
_HOLD_BEFORE_AUDIT_SECONDS = 60


def held_for_arrival(key: str, received_iso: str) -> dict[str, Any] | None:
    """The page held for the arrival audited at `received_iso` under `key`,
    or None when that arrival held none."""
    if not key or not received_iso:
        return None
    received = datetime.fromisoformat(received_iso)
    earliest = (received - timedelta(seconds=_HOLD_BEFORE_AUDIT_SECONDS)).isoformat()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT held_at, released_at, dropped_because FROM page_hold "
            "WHERE key = ? AND held_at <= ? AND held_at >= ? "
            "ORDER BY held_at DESC, id DESC LIMIT 1",
            (key, received_iso, earliest),
        ).fetchone()
    return dict(row) if row else None


def last_released_text(key: str) -> str | None:
    """The words of the newest page under `key` that really went out, or None."""
    if not key:
        return None
    with get_connection() as conn:
        row = conn.execute(
            "SELECT text FROM page_hold WHERE key = ? AND released_at IS NOT NULL "
            "AND dropped_because IS NULL ORDER BY released_at DESC, id DESC LIMIT 1",
            (key,),
        ).fetchone()
    return str(row[0]) if row else None


def recent_held(limit: int = 10) -> list[dict[str, Any]]:
    """The pages waiting right now, newest first, for the don't-repeat-yourself
    block the two model loops paste into their prompts.

    Load-bearing rather than convenient. Triage decides whether to speak by
    reading what the assistant already said, through `outbound.recent_sent`, which reads
    `chat_turns`, which is written only after a successful send. Hold a page and
    it is not there, so triage stops seeing "already paged" and stops silencing
    the follow-ups, most of which cite a page a hold would have prevented, so
    without this the morning release would carry several times as many
    drafts.
    """
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM page_hold WHERE released_at IS NULL "
            "ORDER BY held_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def dropped_since(since_iso: str, limit: int = 20) -> list[dict[str, Any]]:
    """Pages held at or after `since_iso` that were taken out of the queue
    unsent, oldest first, each with its `dropped_because`.

    The morning brief lists them: an outage that ended overnight is a
    line in the morning report, not a page, and without this read it is
    neither.
    """
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM page_hold WHERE dropped_because IS NOT NULL AND held_at >= ? "
            "ORDER BY held_at, id LIMIT ?",
            (since_iso, limit),
        ).fetchall()
    return [dict(row) for row in rows]
