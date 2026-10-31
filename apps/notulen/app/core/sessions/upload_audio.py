"""Push a session's assembled audio to S3 and record the key on the job row.

Owns the S3 key grammar ``notulen/audio/<job_id>.webm``. Does NOT own the
tempfile layout (``core/sessions/files.py``) or the S3 client wiring
(``shared/s3.py``).

FAILURE POLICY: Tier-1: both the S3 upload and the job-row update
propagate (the recording IS the product).
"""
from __future__ import annotations

from apps.notulen.app.core.sessions.files import session_files
from apps.notulen.app.shared.config import S3_BUCKET
from apps.notulen.app.shared.s3 import get_s3
from apps.notulen.app.shared.update_job import update_job


def upload_assembled_to_s3(job_id: str) -> str:
    """Upload the assembled session audio; return its S3 key."""
    audio_path = session_files(job_id).audio_path
    s3_key = f"notulen/audio/{job_id}.webm"
    get_s3().upload_file(str(audio_path), S3_BUCKET, s3_key)
    update_job(job_id, s3_audio_key=s3_key)
    return s3_key
