"""Pages for the ways a meeting recording can be lost.

Owns the page copy for a live browser recording that stopped sending audio,
a GPU transcription job that died before writing its row, a Talk call whose
recording never started, and a Talk call that ended with no recording. Every page goes
to the assistant's notify door (``shared/assistant_door.py``), which decides
how it reaches the owner. The notifier is an injectable collaborator so a
test can capture the page without a running assistant.

FAILURE POLICY: Tier-2 swallow. A broken page path must never break the watch
loops that call these; a page that cannot go out is logged, not raised.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

from apps.notulen.app.shared.assistant_door import notify_assistant

logger = logging.getLogger("notulen")


def alert_recording_stalled(
    job_id: str,
    title: str,
    quiet_secs: float,
    *,
    notifier: Callable[[str, str], None] = notify_assistant,
) -> None:
    """Page when a live browser recording stopped delivering chunks."""
    try:
        notifier(
            "notulen: recording stopped sending audio",
            f"Recording \"{title}\" ({job_id}) has sent no audio to the "
            f"server for about {quiet_secs / 60:.0f} min and was not finalized.\n\n"
            "If the meeting is still going, check the recording phone now "
            "(microphone permission lost, battery dead, browser closed?). "
            "Audio received so far is safe; the session can be finalized with "
            "what there is from the dashboard.",
        )
    except Exception:
        # Tier-2 swallow: a broken notifier must not break the watch loop.
        logger.exception("Failed to page on stalled recording %s", job_id)


def alert_gpu_job_died(
    job_id: str,
    title: str,
    reason: str,
    *,
    notifier: Callable[[str, str], None] = notify_assistant,
) -> None:
    """Page when a GPU transcription Job failed before writing its row."""
    try:
        notifier(
            "notulen: transcription stopped",
            f"The GPU job for \"{title}\" ({job_id}) stopped before the "
            f"minutes were written.\n\nReason: {reason}\n\n"
            "The audio is safe in S3 and the job is marked failed, so it can "
            "be retried from the dashboard. A deadline on a job that never "
            "started usually means no GPU was available in the pool's zone.",
        )
    except Exception:
        # Tier-2 swallow: a broken notifier must not break the watch loop.
        logger.exception("Failed to page on dead GPU job %s", job_id)


def alert_recording_not_started(
    token: str,
    reason: str,
    *,
    notifier: Callable[[str, str], None] = notify_assistant,
) -> None:
    """Page when the recording could not be started for an active Talk call."""
    try:
        notifier(
            "notulen: Talk recording failed to start",
            f"Auto-recording never started for Talk call {token}, so no "
            f"minutes will be written.\n\nReason: {reason}\n\n"
            "The call happened but was not recorded. If this recurs, check "
            "that the assistant's Nextcloud account can start recordings (it "
            "owns the room, the call is in progress) and that the media box's "
            "recording server is up.",
        )
    except Exception:
        # Tier-2 swallow: a broken notifier must not break the webhook path.
        logger.exception("Failed to page on recording-not-started for %s", token)


def alert_no_recording(
    token: str,
    duration_sec: float | None,
    *,
    notifier: Callable[[str, str], None] = notify_assistant,
) -> None:
    """Page when a real Talk call ended and no recording was found to ingest."""
    minutes = "unknown" if duration_sec is None else f"{duration_sec / 60:.0f}"
    try:
        notifier(
            "notulen: call ended with no recording",
            f"Talk call {token} ended after about {minutes} min but produced no "
            "recording, so no minutes were written.\n\n"
            "This is a real meeting lost. Check the media box's recording "
            "server and whether the recording started for this call.",
        )
    except Exception:
        # Tier-2 swallow: a broken notifier must not break the ingest thread.
        logger.exception("Failed to page on no-recording for %s", token)
