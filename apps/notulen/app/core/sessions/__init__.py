"""Recording-session lifecycle (``core/sessions/``).

Module map (one public callable per file):
    files.py         : session_files(job_id) -> SessionFiles (tempdir store)
    upload_audio.py  : upload_assembled_to_s3(job_id) -> s3_key
    stale_cleanup.py : cleanup_stale_recordings_loop() daemon (6 h retirement)
    retire_session.py: retire_stale_session(job_id) (keeps the audio)
    recovery.py      : recover_interrupted_jobs() startup orphan sweep
    stall_watch.py   : watch_stalled_recordings_loop() daemon (quiet-session page)
    dead_gpu_jobs.py : watch_dead_gpu_jobs_loop() daemon (failed GPU Job page)
    stitch.py        : stitch_segments(audio_path) (multi-segment join)
    loudness.py      : ensure_audible(audio_path) (near-silent speech boost)
    attendee_list.py : clean_attendees(names) -> the same people, named once
"""
from __future__ import annotations

from apps.notulen.app.core.sessions.files import (
    SessionFiles,
    session_files,
)
from apps.notulen.app.core.sessions.recovery import (
    recover_interrupted_jobs,
)
from apps.notulen.app.core.sessions.retire_session import (
    retire_stale_session,
)
from apps.notulen.app.core.sessions.stale_cleanup import (
    cleanup_stale_recordings_loop,
)
from apps.notulen.app.core.sessions.stall_watch import (
    watch_stalled_recordings_loop,
)
from apps.notulen.app.core.sessions.stitch import stitch_segments
from apps.notulen.app.core.sessions.upload_audio import (
    upload_assembled_to_s3,
)

__all__ = [
    "SessionFiles",
    "cleanup_stale_recordings_loop",
    "recover_interrupted_jobs",
    "retire_stale_session",
    "session_files",
    "stitch_segments",
    "upload_assembled_to_s3",
    "watch_stalled_recordings_loop",
]
