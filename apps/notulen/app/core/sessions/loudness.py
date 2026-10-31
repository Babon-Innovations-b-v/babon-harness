"""Loudness gate for assembled session audio.

Owns the near-silent detection + speech boost that runs at finalize,
before the S3 upload. A collapsed iOS mic level can produce a near-silent
recording that whisper's VAD strips to nothing after a full GPU spin-up. Does NOT own the tempfile layout
(``core/sessions/files.py``) or the S3 upload (``core/sessions/upload_audio.py``).

FAILURE POLICY: fail-open throughout: the recording is the product. If
ffmpeg is missing or errors, finalize proceeds with the original audio and
the caller logs; a failed boost must never lose a meeting.
"""
from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Below this mean level the recording is treated as near-silent. Normal
# meeting audio measures around -35..-20 dB mean; a collapsed-mic recording
# sits far below this threshold even where speech is present.
NEAR_SILENT_MEAN_DB = -50.0

_MEAN_VOLUME_RE = re.compile(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")


def parse_mean_volume(ffmpeg_stderr: str) -> float | None:
    """Extract the mean_volume figure from ffmpeg volumedetect output."""
    match = _MEAN_VOLUME_RE.search(ffmpeg_stderr)
    return float(match.group(1)) if match else None


def measure_mean_volume_db(audio_path: Path) -> float | None:
    """Mean loudness of the file in dB, or None if ffmpeg fails."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", str(audio_path),
             "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True, timeout=600,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("volumedetect failed for %s: %s", audio_path, exc)
        return None
    return parse_mean_volume(result.stderr)


def boost_speech(audio_path: Path) -> bool:
    """Re-encode near-silent audio with a speech-level boost, in place.

    Returns True if the file was replaced. On any ffmpeg failure the
    original file is left untouched and False is returned.
    """
    boosted_path = audio_path.with_suffix(".boosted.webm")
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-y", "-i", str(audio_path),
             "-af", "highpass=f=60,speechnorm=e=25:r=0.0005:l=1",
             "-c:a", "libopus", "-b:a", "64k", "-ar", "48000", "-ac", "1",
             str(boosted_path)],
            capture_output=True, text=True, timeout=1800,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("speech boost failed for %s: %s", audio_path, exc)
        boosted_path.unlink(missing_ok=True)
        return False
    if result.returncode != 0 or not boosted_path.exists() or boosted_path.stat().st_size == 0:
        logger.warning("speech boost failed for %s: %s", audio_path, result.stderr[-500:])
        boosted_path.unlink(missing_ok=True)
        return False
    boosted_path.replace(audio_path)
    return True


def ensure_audible(audio_path: Path) -> None:
    """Boost the file in place when it measures near-silent; fail-open."""
    mean_db = measure_mean_volume_db(audio_path)
    if mean_db is None or mean_db >= NEAR_SILENT_MEAN_DB:
        return
    logger.warning(
        "near-silent recording (%.1fdB mean) at %s: applying speech boost",
        mean_db, audio_path,
    )
    boost_speech(audio_path)
