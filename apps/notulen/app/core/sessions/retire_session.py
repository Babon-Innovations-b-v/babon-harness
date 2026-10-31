"""Close out a recording session that will never be finalized.

A session still in ``recording`` past the staleness cutoff can hold a real
meeting on disk: someone forgot to press stop, or the tab died after the
last chunk landed. This module owns the one rule that matters there: audio
leaves the disk only once it exists in S3.
A retired session that held audio is left ``failed`` with its
``s3_audio_key`` set, so ``POST /api/jobs/{id}/retry`` can still turn it
into minutes. Does NOT own the staleness policy (``stale_cleanup.py``) or
the S3 key grammar (``upload_audio.py``).

FAILURE POLICY: Tier-1: the S3 upload and the row update propagate; the
caller's loop swallows per tick and the tempfile is still on disk, so the
next tick retries the same session.
"""
from __future__ import annotations

from apps.notulen.app.core.sessions.files import session_files
from apps.notulen.app.core.sessions.stitch import stitch_segments
from apps.notulen.app.core.sessions.upload_audio import (
    upload_assembled_to_s3,
)
from apps.notulen.app.shared.update_job import update_job

TIMED_OUT_WITH_AUDIO = (
    "Recording not finished (session expired); the audio is kept and can be retried"
)
TIMED_OUT_EMPTY = "Recording session timed out"


def retire_stale_session(job_id: str) -> None:
    """Retire a forgotten recording session, keeping whatever audio it holds."""
    files = session_files(job_id)
    holds_audio = files.audio_path.exists() and files.audio_path.stat().st_size > 0
    if holds_audio:
        # A self-healed recorder can leave multiple container
        # segments in the append file; join them before the audio becomes
        # the retryable S3 copy. Fail-open like finalize.
        stitch_segments(files.audio_path)
        upload_assembled_to_s3(job_id)
        update_job(job_id, status="failed", error=TIMED_OUT_WITH_AUDIO)
    else:
        update_job(job_id, status="aborted", error=TIMED_OUT_EMPTY)
    files.cleanup()
