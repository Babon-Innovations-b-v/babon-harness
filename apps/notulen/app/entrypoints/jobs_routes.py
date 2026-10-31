"""Job read/retry/delete routes (GET/POST/DELETE /api/jobs*).

Owns the JSON projection of ``notulen_jobs`` rows, the retry policy for
failed jobs, and the deletion policy. Does NOT own row writes
(``shared/update_job.py``) or the pipeline.

FAILURE POLICY: DB unavailability is 503 on detail routes; the list route
returns an empty list (fail-open read: the SPA shows "No recordings yet"
rather than an error page, and its polling makes a 5xx storm worse than a
blank list). Deletion is fail-closed: the S3 audio delete propagates, so we
never claim deleted while the (privacy-relevant) audio object remains.
"""
from __future__ import annotations

import threading

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from dashkit.core import audit as _audit
from dashkit.core.db import get_db

from apps.notulen.app.core.minutes.process_job import process_job
from apps.notulen.app.core.publish.github.remove_notulen import (
    remove_notulen,
)
from apps.notulen.app.shared.config import S3_BUCKET
from apps.notulen.app.shared.identity import who
from apps.notulen.app.shared.jobs_table import ensure_jobs_table
from apps.notulen.app.shared.s3 import get_s3
from apps.notulen.app.shared.slug import slugify
from apps.notulen.app.shared.update_job import update_job

router = APIRouter()


@router.get("/api/jobs")
def _list_jobs(limit: int = 50):
    conn = get_db()
    if not conn:
        # Documented fail-open read: the SPA polls this every 5s; render an
        # empty list rather than an error storm. Detail routes 503 instead.
        return {"jobs": []}
    try:
        ensure_jobs_table(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, status, title, meeting_date, attendees, duration_secs, "
                "error, created_by, created_at, completed_at "
                "FROM notulen_jobs ORDER BY created_at DESC LIMIT %s",
                (min(max(limit, 1), 200),),
            )
            return {
                "jobs": [
                    {
                        "id": str(row[0]),
                        "status": row[1],
                        "title": row[2],
                        "meeting_date": row[3].isoformat() if row[3] else None,
                        "attendees": row[4] or [],
                        "duration_secs": row[5],
                        "error": row[6],
                        "created_by": row[7],
                        "created_at": row[8].isoformat() if row[8] else None,
                        "completed_at": row[9].isoformat() if row[9] else None,
                    }
                    for row in cur.fetchall()
                ]
            }
    finally:
        conn.close()


@router.get("/api/jobs/{job_id}")
def _get_job(job_id: str):
    conn = get_db()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        ensure_jobs_table(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, status, title, meeting_date, attendees, duration_secs, "
                "transcript_text, output_markdown, error, created_by, created_at, "
                "completed_at, output_path, board_issues "
                "FROM notulen_jobs WHERE id = %s",
                (job_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Job not found")
            return {
                "id": str(row[0]),
                "status": row[1],
                "title": row[2],
                "meeting_date": row[3].isoformat() if row[3] else None,
                "attendees": row[4] or [],
                "duration_secs": row[5],
                "transcript": row[6],
                "notulen": row[7],
                "error": row[8],
                "created_by": row[9],
                "created_at": row[10].isoformat() if row[10] else None,
                "completed_at": row[11].isoformat() if row[11] else None,
                # `notulen` above is the machine's first draft and stays that
                # way for ever; `editable` says whether the SPA can open the
                # committed file, which is the version anybody has corrected.
                "editable": bool(row[12]),
                "sent_to_assistant": row[13] is not None,
                "board_issues": row[13] or [],
            }
    finally:
        conn.close()


@router.post("/api/jobs/{job_id}/retry")
def _retry_job(job_id: str, request: Request):
    """Re-run the pipeline for a failed job whose audio is already in S3.

    Only `failed` rows with an `s3_audio_key` qualify; anything else 409s so
    the browser state machine stays simple.
    """
    user = who(request)
    conn = get_db()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        ensure_jobs_table(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status, s3_audio_key, title, meeting_date, attendees, agenda "
                "FROM notulen_jobs WHERE id = %s",
                (job_id,),
            )
            row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Job not found")
        status, s3_key, title, meeting_date, attendees, agenda = row
        if status != "failed":
            raise HTTPException(
                status_code=409,
                detail=f"Only failed jobs can be retried (status={status})",
            )
        if not s3_key:
            raise HTTPException(
                status_code=409, detail="No audio in S3 to retry from"
            )
        _audit.log_activity(
            conn, "notulen_activity",
            "notulen_retried", user,
            detail={"job_id": job_id, "title": title},
        )
        conn.commit()
    finally:
        conn.close()

    # Clear the previous run's commit URL too: the git writer loop skips
    # rows that already have one, so a retried job would otherwise finish
    # its pipeline and then hang in `committing` forever.
    update_job(job_id, status="pending", error=None, output_commit_url=None)
    date_str = meeting_date.isoformat() if meeting_date else ""
    thread = threading.Thread(
        target=process_job,
        args=(job_id, s3_key, title, date_str, list(attendees or []), agenda or ""),
        daemon=True,
    )
    thread.start()
    return {"ok": True, "job_id": job_id}


@router.delete("/api/jobs/{job_id}")
def _delete_job(job_id: str, request: Request):
    """Delete a recording: its row, its S3 audio, and its committed minutes.

    A file left behind would be invisible from the dashboard and would hold
    its name, pushing that day's real meeting onto a `-2` file.

    The three deletes fail differently on purpose. The audio is
    privacy-relevant, so a failure there aborts the whole request rather than
    reporting a delete that left the recording in S3. The row is the state.
    The markdown is only untidy if it lingers, so a GitHub outage does not
    stop somebody removing a recording; the answer says whether it went.
    """
    user = who(request)
    conn = get_db()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        ensure_jobs_table(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT s3_audio_key, title, meeting_date, output_path "
                "FROM notulen_jobs WHERE id = %s",
                (job_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Job not found")
            s3_key, title, meeting_date, output_path = row

            # Fail-closed: if the audio object can't be deleted, abort the
            # whole delete (500) so we never report success while the
            # recording still sits in S3. S3 deletes are idempotent, so the
            # user's retry converges.
            if s3_key:
                get_s3().delete_object(Bucket=S3_BUCKET, Key=s3_key)

            cur.execute("DELETE FROM notulen_jobs WHERE id = %s", (job_id,))

        # Last, and Tier-2: the row is already gone, so a file left behind is
        # untidy rather than a lie about where the recording is.
        minutes_removed = remove_notulen(
            output_path or "",
            f"notulen: remove {title} ({meeting_date}), deleted by {user} "
            f"[job:{job_id}]",
        )
        _audit.log_activity(
            conn, "notulen_activity",
            "notulen_deleted", user,
            detail={
                "job_id": job_id, "title": title,
                "path": output_path, "minutes_removed": minutes_removed,
            },
        )
        conn.commit()
        return {"ok": True, "minutes_removed": minutes_removed}
    finally:
        conn.close()


@router.get("/api/jobs/{job_id}/download")
def _download_notulen(job_id: str):
    conn = get_db()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        ensure_jobs_table(conn)
        with conn.cursor() as cur:
            # Markdown is downloadable as soon as it exists, even while the
            # job is still `committing` (awaiting its git commit): nobody
            # should wait on git to grab their own minutes.
            cur.execute(
                "SELECT title, meeting_date, output_markdown FROM notulen_jobs "
                "WHERE id = %s AND output_markdown IS NOT NULL",
                (job_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Notulen not found or not ready")
            title, meeting_date, markdown = row
            month = meeting_date.isoformat()[:7]
            filename = f"{month}_{slugify(title)}.md"
            return Response(
                content=markdown,
                media_type="text/markdown; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
    finally:
        conn.close()
