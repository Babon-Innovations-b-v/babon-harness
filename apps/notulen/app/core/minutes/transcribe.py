"""CPU whisper transcription, the path every recording takes without a GPU.

The dashboard runs whisper on its own CPU when the GPU tier is off
(``GPU_ENABLED=0``) or a dispatch failed. It needs the ``whisper`` extra
(``faster-whisper``), which the dashboard image installs. Speaker diarization
is GPU-only, so this path returns transcripts without speaker labels. The
model size is ``NOTULEN_CPU_MODEL`` (default ``medium``); the spoken language
is ``NOTULEN_LANGUAGE`` (a whisper language code, empty to auto-detect).

Twin declaration: the GPU path in ``apps/notulen/entrypoints/worker.py``
carries its own transcription (whisper-large-v3 plus pyannote) by design. The
worker image is a self-contained unit with no package imports, so the
block-formatting grammar is deliberately duplicated there.

FAILURE POLICY: Tier-1. Model and transcription errors propagate and
``process_job`` marks the job ``failed``. faster_whisper imports lazily so the
dashboard boots without it loaded.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger("notulen")

# Silence longer than this starts a new transcript block.
PAUSE_THRESHOLD_SEC = 2.0


def _format_ts(seconds: float) -> str:
    """Format seconds as [MM:SS]."""
    minutes, secs = divmod(int(seconds), 60)
    return f"[{minutes:02d}:{secs:02d}]"


def transcribe_cpu(wav_path: Path) -> tuple[str, float]:
    """Transcribe a WAV file with whisper (CPU).

    Returns (transcript_text, duration_seconds).
    """
    import gc  # noqa: PLC0415
    from faster_whisper import WhisperModel  # noqa: PLC0415 (heavy, the whisper extra)

    model_size = os.environ.get("NOTULEN_CPU_MODEL", "medium")
    logger.info("Loading whisper %s model (int8, CPU)...", model_size)
    model = WhisperModel(model_size, compute_type="int8", device="cpu")
    logger.info("Whisper model loaded.")

    try:
        segments, info = model.transcribe(
            str(wav_path), language=os.environ.get("NOTULEN_LANGUAGE") or None, beam_size=5,
            vad_filter=True, word_timestamps=True,
        )

        blocks: list[str] = []
        current_block: list[str] = []
        block_start: float = 0.0
        prev_end: float = 0.0

        for segment in segments:
            # New block on pause
            if current_block and segment.start - prev_end > PAUSE_THRESHOLD_SEC:
                blocks.append(f"{_format_ts(block_start)} {' '.join(current_block)}")
                current_block = []
                block_start = segment.start

            if not current_block:
                block_start = segment.start

            current_block.append(segment.text.strip())
            prev_end = segment.end

        if current_block:
            blocks.append(f"{_format_ts(block_start)} {' '.join(current_block)}")

        transcript = "\n\n".join(blocks)
        return transcript, info.duration
    finally:
        del model
        gc.collect()
        logger.info("Whisper model unloaded.")
