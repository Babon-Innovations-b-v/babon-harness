"""The test-and-set that makes "send to the assistant" fire once.

Pressing the button twice would put a whole meeting on the board twice, under
real parents, with real assignees. This makes "once" true rather than hoped
for.

The claim is taken BEFORE the assistant is called, not after it answers. The
assistant does minutes of work behind that call, so a claim written on the
way out leaves a window where a second press starts a second run; and a
caller that cannot tell whether it already sent must not send.

Releasing is not a function here: a caller that learns the assistant never
started clears the stamp with the ordinary `update_job(job_id, board_sent_at=None)`.

FAILURE POLICY: Tier-1. An unavailable database raises rather than returning
False, because False here means "already sent" and a database fault must
never be read as that.
"""
from __future__ import annotations

from dashkit.core.db import get_db

from apps.notulen.app.shared.jobs_table import ensure_jobs_table


def claim_send(job_id: str) -> bool:
    """True when this call is the one that gets to send the meeting.

    False means the button already fired for this notulen, whether a second
    ago or last week. The check and the write are one statement, so two
    presses that arrive together cannot both win.

    Raises:
        RuntimeError: the database is unavailable.
        LookupError: no such job.
    """
    conn = get_db()
    if not conn:
        raise RuntimeError("cannot claim the send: database unavailable")
    try:
        ensure_jobs_table(conn)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE notulen_jobs SET board_sent_at = NOW() "
                "WHERE id = %s AND board_sent_at IS NULL RETURNING id",
                (job_id,),
            )
            won = cur.fetchone() is not None
            if not won:
                cur.execute("SELECT id FROM notulen_jobs WHERE id = %s", (job_id,))
                if cur.fetchone() is None:
                    raise LookupError(f"no notulen job {job_id}")
        conn.commit()
        return won
    finally:
        conn.close()
