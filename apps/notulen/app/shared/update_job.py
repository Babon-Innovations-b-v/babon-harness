"""Parameterised UPDATE for ``notulen_jobs`` rows.

Owns: the column allowlist (SQL-injection guardrail) and the UPDATE
statement. Does NOT own the schema (``shared/jobs_table.py``) or any
SELECT: readers query through their own cursors.

FAILURE POLICY: Tier-1: job-row updates are structural state (a status
flip is what makes a set of minutes visible or retriable), so failures
propagate. A silently dropped write could strand committed minutes in
``committing`` or hide a failure; callers get the exception instead: routes
500, the daemon loops log and retry on their next tick, ``process_job`` marks
the job failed.
"""
from __future__ import annotations

from dashkit.core.db import get_db

from apps.notulen.app.shared.jobs_table import ensure_jobs_table

# Columns allowed in update_job. Interpolating a dict key into raw SQL
# is a classic injection footgun. Allowlist at the DB boundary so an
# attacker-influenced key can never reach SQL.
UPDATABLE_JOB_COLUMNS = frozenset({
    "status", "error",
    "transcript_text", "duration_secs",
    "output_markdown", "completed_at",
    "s3_audio_key",
    "last_chunk_seq", "agenda",
    "output_commit_url", "output_path",
    "last_chunk_at", "stall_paged_at",
    "board_sent_at", "board_issues",
})


def update_job(job_id: str, **fields) -> None:
    """Update allowlisted job fields. No-op when no fields are given.

    Raises ``ValueError`` on a non-allowlisted column (programmer error,
    fail loud) and ``RuntimeError`` when the DB is unavailable.
    """
    if not fields:
        return
    bad = set(fields) - UPDATABLE_JOB_COLUMNS
    if bad:
        raise ValueError(
            f"Refusing to update notulen_jobs: unknown columns {sorted(bad)}"
        )
    conn = get_db()
    if not conn:
        raise RuntimeError("notulen_jobs update failed: database unavailable")
    try:
        ensure_jobs_table(conn)
        # Column names are safe (allowlisted above); values go through
        # psycopg parameter substitution.
        sets = ", ".join(f'"{column}" = %s' for column in fields)
        vals = list(fields.values())
        vals.append(job_id)
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE notulen_jobs SET {sets} WHERE id = %s", vals
            )
        conn.commit()
    finally:
        conn.close()
