"""Notulen domain logic (the ``core/`` layer), grouped into role subdirs.

    minutes/  : audio to minutes (transcribe, generate, GPU dispatch,
                 the per-upload state machine)
    publish/  : git publication: complete means committed
    board/    : hand corrected minutes to the assistant, once
    sessions/ : recording-session lifecycle (tempfiles, S3 upload,
                 stale retirement, startup crash recovery)

This seam re-exports what the ``entrypoints/`` layer consumes; pipeline
steps (transcribe_cpu, generate_notulen, try_dispatch_gpu, finalize_commit)
stay subpackage-internal: callers want the state machine, not its steps.
"""
from __future__ import annotations

from apps.notulen.app.core.minutes.process_job import process_job
from apps.notulen.app.core.publish.retry.git_writer_loop import git_writer_loop
from apps.notulen.app.core.sessions.files import session_files
from apps.notulen.app.core.sessions.recovery import (
    recover_interrupted_jobs,
)
from apps.notulen.app.core.sessions.stale_cleanup import (
    cleanup_stale_recordings_loop,
)
from apps.notulen.app.core.sessions.upload_audio import (
    upload_assembled_to_s3,
)

__all__ = [
    "cleanup_stale_recordings_loop",
    "git_writer_loop",
    "process_job",
    "recover_interrupted_jobs",
    "session_files",
    "upload_assembled_to_s3",
]
