"""`filed_observations` table adapter, what the assistant has already put on the board.

Storage-grammar table adapter (blueprint 2.3): the table's writes and reads
live together.

WHY THIS EXISTS AND IS NOT `suppression`. When a subject keeps coming back,
the assistant opens one backlog card for it and then stops raising it. Reusing
`state.add_suppression` for that looks natural and is wrong, in a way that
could be expensive.

`suppression` is the ALERT pipeline's mute: `triage` consults it and returns
`silent` without an LLM call, so a suppressed pattern never pages at all. Using
it here would conflate two different things. "the assistant has said this once and will not
say it again" is about the assistant's messages. "This alert must not page" is about
the alert pipeline, and only a human should decide it. A filer using it could
suppress `ResourceHigh`, which is five Prometheus rules under one name up to
the critical disk-full page, or the deploy gate's own verification
failure. Both are the same mistake: silencing an alert in order
to quieten a message.

So this table mutes the MESSAGE and nothing else. The notify pen stops paging
about a filed subject; Alertmanager triage never looks here; a real alert still
pages exactly as before.

And it EXPIRES. `amtool silence add` defaults to one hour and offers no
never-expires flag, and Grafana silences carry a fixed end while still
evaluating the rule underneath. A mute with no end is a decision nobody revisits
and nobody remembers making. Ours ends, and the thing comes back if it is still
happening.

FAILURE POLICY: Tier-1 fail-loud, like every adapter here. A failed
write propagates; the caller decides.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from apps.assistant.core.state.conn import get_connection
from apps.assistant.core.state.utcnow_iso import utcnow_iso

# How long the assistant stays quiet about something it has filed. Long enough that the
# card is the working record, short enough that a mute is not permanent.
FILED_TTL_DAYS = 90


def _key(subject: str) -> str:
    """`subject` as the mute key every row here is written and matched under.

    Imported at call time because `ping_facts` imports this package: the key is
    cut by the same `split_subject` the page and the audit row are cut by, and a
    second copy of that rule here would drift from it.
    """
    from apps.assistant.core.ping_facts import mute_key

    return mute_key(subject)


def _stored_spellings(subject: str) -> list[str]:
    """Every stored subject that is the same mute as `subject`, newest first.

    Matched on the key in Python rather than on the column in SQL, because rows
    written before the key existed carry the sender's marker ("⚠️ ...", "🔴
    ...") and an exact match on either spelling misses the other. The table
    holds one row per card the assistant ever filed, a few dozen, so the scan is free.
    """
    wanted = _key(subject)
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT subject FROM filed_observations ORDER BY filed_at DESC"
        ).fetchall()
    return [row["subject"] for row in rows if _key(row["subject"]) == wanted]


def record_filed(subject: str, issue_number: int, ttl_days: int = FILED_TTL_DAYS) -> None:
    """Remember that `subject` is on the board, and until when.

    Written under the mute key, whatever spelling the caller holds, so no
    caller can store a key that a lookup from a differently marked ping misses.
    """
    now = datetime.now(timezone.utc)
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO filed_observations "
            "(subject, issue_number, filed_at, expires_at) VALUES (?, ?, ?, ?)",
            (
                _key(subject),
                int(issue_number),
                utcnow_iso(),
                (now + timedelta(days=ttl_days)).isoformat(),
            ),
        )
        conn.commit()


def clear_filed(subject: str) -> bool:
    """Lift the mute on `subject`. True when a row was there to lift.

    A MUTE WITH NO WAY TO LIFT IT IS A TRAP. Without this, the only ways out
    would be waiting ninety days or editing the container's SQLite by hand,
    neither of which is a thing to reach for at the moment you discover a mute
    is wrong.

    The case that makes it urgent: a card muting a subject such as
    `dependency scan found vulnerabilities`, which is a CATEGORY whose content differs every time: a
    different package and a different CVE per run. Closing the issue does not
    touch this table, so the subject would have stayed silent for the whole mute
    and a brand-new vulnerability in a dependency would have produced no message
    for three months. That is the one case where a mute is worse than the noise
    it removes.

    The row is DELETED rather than expired in place, unlike the lapsed rows
    `list_filed` deliberately keeps. A lapsed mute is a record of a decision
    that ran its course; a lifted one is a decision reversed, and leaving a
    tombstone that reads like the first would misdescribe it. The issue is the
    record of why it was filed, and the log line at the call site is the record
    of why it was lifted.

    The lift's TIME is kept, in `mute_lifts`, and nothing else is. Without it
    the filer would re-read the same window that produced the card and file it
    again at the next beat. `last_decision_at` hands the
    time to the filer, which counts only what arrived after it.
    """
    spellings = _stored_spellings(subject)
    if not spellings:
        return False
    marks = ", ".join("?" for _ in spellings)
    with get_connection() as conn:
        conn.execute(
            f"DELETE FROM filed_observations WHERE subject IN ({marks})", spellings
        )
        conn.execute(
            "INSERT OR REPLACE INTO mute_lifts (subject, lifted_at) VALUES (?, ?)",
            (_key(subject), utcnow_iso()),
        )
        conn.commit()
    return True


def last_decision_at(subject: str) -> str | None:
    """When a decision about `subject` last ended its history, or None.

    The latest of: a lift, a filing (live or lapsed), and a lapse. An
    occurrence at or before this time has already been decided on, so the
    recurring filer may not count it towards a new card; a lifted or lapsed
    subject needs fresh days of its own before it is filed again.
    """
    wanted = _key(subject)
    now = utcnow_iso()
    with get_connection() as conn:
        filed = conn.execute(
            "SELECT subject, filed_at, expires_at FROM filed_observations"
        ).fetchall()
        lifts = conn.execute("SELECT subject, lifted_at FROM mute_lifts").fetchall()
    moments = [row["lifted_at"] for row in lifts if _key(row["subject"]) == wanted]
    for row in filed:
        if _key(row["subject"]) != wanted:
            continue
        moments.append(row["filed_at"])
        if row["expires_at"] <= now:
            moments.append(row["expires_at"])
    return max(moments) if moments else None


def filed_issue_for(subject: str) -> int | None:
    """The issue number the assistant filed for `subject`, or None when it is not filed
    or the entry has expired. Any spelling of the subject finds it (`_key`)."""
    wanted = _key(subject)
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT subject, issue_number FROM filed_observations "
            "WHERE expires_at > ? ORDER BY filed_at DESC",
            (utcnow_iso(),),
        ).fetchall()
    for row in rows:
        if _key(row["subject"]) == wanted:
            return int(row["issue_number"])
    return None


def list_filed(include_expired: bool = False) -> list[dict[str, Any]]:
    """Every filed subject, newest first. Expired rows are kept on purpose: the
    record of what was muted, and when it lapsed, is worth as much as the mute."""
    query = "SELECT * FROM filed_observations"
    params: tuple = ()
    if not include_expired:
        query += " WHERE expires_at > ?"
        params = (utcnow_iso(),)
    query += " ORDER BY filed_at DESC"
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]
