"""Schema bootstrap for the ``notulen_jobs`` table.

Owns: CREATE TABLE, the idempotent column additions, and the
complete-means-committed backfill. Does NOT own row updates (``shared/update_job.py``) or row reads
(route modules query through their own cursors).

FAILURE POLICY: Tier-1: DDL errors propagate. A dashboard that
cannot bootstrap its table must fail its request loudly, not render an
empty job list.
"""
from __future__ import annotations

_jobs_table_ready = False


def ensure_jobs_table(conn) -> None:
    """Create/upgrade ``notulen_jobs`` once per process. Caller owns ``conn``."""
    global _jobs_table_ready
    if _jobs_table_ready:
        return
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS notulen_jobs (
                id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                status          TEXT NOT NULL DEFAULT 'pending',
                title           TEXT NOT NULL,
                meeting_date    DATE NOT NULL,
                attendees       TEXT[],
                duration_secs   INTEGER,
                s3_audio_key    TEXT,
                transcript_text TEXT,
                output_markdown TEXT,
                error           TEXT,
                created_by      TEXT NOT NULL DEFAULT 'anonymous',
                created_at      TIMESTAMPTZ DEFAULT NOW(),
                completed_at    TIMESTAMPTZ,
                last_chunk_seq  INTEGER,
                agenda          TEXT
            )
        """)
        # Live-table additions (idempotent): pre-existing deployments add the
        # columns on first boot after this change ships.
        cur.execute(
            "ALTER TABLE notulen_jobs ADD COLUMN IF NOT EXISTS last_chunk_seq INTEGER"
        )
        cur.execute(
            "ALTER TABLE notulen_jobs ADD COLUMN IF NOT EXISTS agenda TEXT"
        )
        cur.execute(
            "ALTER TABLE notulen_jobs ADD COLUMN IF NOT EXISTS output_commit_url TEXT"
        )
        # Stall watch: when the last chunk landed, and whether this
        # session's went-quiet page already fired (one page per session).
        cur.execute(
            "ALTER TABLE notulen_jobs ADD COLUMN IF NOT EXISTS last_chunk_at TIMESTAMPTZ"
        )
        cur.execute(
            "ALTER TABLE notulen_jobs ADD COLUMN IF NOT EXISTS stall_paged_at TIMESTAMPTZ"
        )
        # Where the minutes landed. The slot walk means the path is
        # not derivable from the title and the date, so without this column
        # the only record of a notulen's file was a commit URL and nothing
        # could reopen it to correct it.
        cur.execute(
            "ALTER TABLE notulen_jobs ADD COLUMN IF NOT EXISTS output_path TEXT"
        )
        # The send-to-assistant button is one-shot: the stamp is the claim
        # that it fired, taken BEFORE the assistant is called so a timeout
        # cannot let a second press open the same meeting twice, and the
        # numbers are what the page shows in place of the button afterwards.
        cur.execute(
            "ALTER TABLE notulen_jobs ADD COLUMN IF NOT EXISTS board_sent_at TIMESTAMPTZ"
        )
        cur.execute(
            "ALTER TABLE notulen_jobs ADD COLUMN IF NOT EXISTS board_issues INTEGER[]"
        )
        # The Talk recording a job was made from, so one recording never
        # becomes two jobs (core/sessions/ingest_recording.py).
        cur.execute(
            "ALTER TABLE notulen_jobs ADD COLUMN IF NOT EXISTS source_path TEXT"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS notulen_jobs_created_idx "
            "ON notulen_jobs (created_at DESC)"
        )
        # `complete` means committed to git. A row marked complete without a
        # commit URL goes back to `committing` so git_writer_loop picks it
        # up. Idempotent: once committed it carries output_commit_url and
        # never matches again.
        cur.execute(
            "UPDATE notulen_jobs SET status = 'committing' "
            "WHERE status = 'complete' "
            "AND output_commit_url IS NULL "
            "AND output_markdown IS NOT NULL"
        )
    conn.commit()
    _jobs_table_ready = True
