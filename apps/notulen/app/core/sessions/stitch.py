"""Stitch a multi-segment assembled recording into one clean file.

A self-healed browser recorder restarts MediaRecorder mid-session
after losing the microphone, so the append-written session tempfile can
carry a fresh container header mid-file. Demuxers stop reading at the
second header, which would silently truncate the notulen to the first
segment. This module finds the segment boundaries and re-encodes the parts
into one continuous file at finalize.

Owns: boundary detection + the ffmpeg concat. Does NOT own the tempfile
layout (``core/sessions/files.py``) or when stitching runs (the finalize
route calls it before the loudness gate).

FAILURE POLICY: fail-open throughout -- the recording is the product. If
ffmpeg is missing or errors, the original file stays in place and the
first segment still transcribes; a failed stitch must never lose a meeting.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger("notulen")

# WebM/Matroska files open with the 4-byte EBML magic. The same 4 bytes can
# occur by chance inside compressed audio, so a match only counts as a
# segment boundary when the EBML header also carries its DocType string
# ("webm"/"matroska") within the next few dozen bytes.
_EBML_MAGIC = b"\x1a\x45\xdf\xa3"
_EBML_DOCTYPE_WINDOW = 64

# MediaRecorder's mp4 output (Safari fallback) opens with an ftyp box: a
# 4-byte big-endian size, then "ftyp". The segment starts at the size field.
_FTYP_MAGIC = b"ftyp"
_FTYP_MAX_BOX_SIZE = 256


def _is_webm_segment_start(data, pos: int) -> bool:
    """True when ``pos`` opens a real EBML header, not a payload collision."""
    window = bytes(data[pos + len(_EBML_MAGIC): pos + _EBML_DOCTYPE_WINDOW])
    return b"webm" in window or b"matroska" in window


def _is_mp4_segment_start(data, pos: int) -> bool:
    """True when the ftyp match at ``pos`` sits at a plausible box start."""
    if pos < 4:
        return False
    box_size = int.from_bytes(bytes(data[pos - 4: pos]), "big")
    return 8 <= box_size <= _FTYP_MAX_BOX_SIZE


def find_segment_offsets(data) -> list[int]:
    """Byte offsets where a new recorder segment starts, first always 0.

    Accepts bytes or an mmap. A single-segment file returns ``[0]``.
    """
    offsets = [0]
    for magic, check, start_delta in (
        (_EBML_MAGIC, _is_webm_segment_start, 0),
        (_FTYP_MAGIC, _is_mp4_segment_start, -4),
    ):
        pos = data.find(magic, 1)
        while pos != -1:
            start = pos + start_delta
            if start > 0 and check(data, pos):
                offsets.append(start)
            pos = data.find(magic, pos + 1)
    return sorted(set(offsets))


def _split_segments(audio_path: Path, data: bytes, offsets: list[int]) -> list[Path]:
    """Write each segment's bytes to its own file next to the original."""
    bounds = offsets + [len(data)]
    parts = []
    for index in range(len(offsets)):
        part = audio_path.with_suffix(f".segment{index:03d}{audio_path.suffix}")
        part.write_bytes(data[bounds[index]:bounds[index + 1]])
        parts.append(part)
    return parts


def _concat_segments(parts: list[Path], out_path: Path) -> bool:
    """ffmpeg-concat the segment files into ``out_path``; False on failure."""
    list_path = out_path.with_suffix(".txt")
    list_path.write_text(
        "".join(f"file '{part}'\n" for part in parts), encoding="utf-8"
    )
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-y", "-f", "concat", "-safe", "0",
             "-i", str(list_path),
             "-c:a", "libopus", "-b:a", "64k", "-ar", "48000", "-ac", "1",
             str(out_path)],
            capture_output=True, text=True, timeout=1800,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("segment concat failed for %s: %s", out_path, exc)
        return False
    finally:
        list_path.unlink(missing_ok=True)
    if result.returncode != 0 or not out_path.exists() or out_path.stat().st_size == 0:
        logger.warning(
            "segment concat failed for %s: %s", out_path, result.stderr[-500:]
        )
        return False
    return True


def stitch_segments(audio_path: Path) -> bool:
    """Join a multi-segment session file in place; True if it was replaced.

    Single-segment files (the normal case) are left untouched. On any
    failure the original file stays in place (fail-open).
    """
    data = audio_path.read_bytes()
    offsets = find_segment_offsets(data)
    if len(offsets) < 2:
        return False
    logger.info(
        "stitching %d recorder segments in %s (offsets %s)",
        len(offsets), audio_path, offsets,
    )
    parts = _split_segments(audio_path, data, offsets)
    stitched_path = audio_path.with_suffix(f".stitched{audio_path.suffix}")
    try:
        if not _concat_segments(parts, stitched_path):
            stitched_path.unlink(missing_ok=True)
            return False
        stitched_path.replace(audio_path)
        return True
    finally:
        for part in parts:
            part.unlink(missing_ok=True)
