"""Audio to minutes pipeline (``core/minutes/``).

Module map (one public callable per file):
    transcribe.py     : transcribe_cpu(wav_path): CPU whisper (the whisper extra)
    notulen_writer.py : generate_notulen(...): Claude transcript→markdown
    gpu_dispatch.py   : try_dispatch_gpu(...): K8s GPU path, fail-open
    process_job.py    : process_job(...): the per-upload state machine
    warm_gpu.py       : warm_gpu(key): hold a GPU while a meeting records
    release_gpu.py    : release_gpu(key): give it back
"""
from __future__ import annotations

from apps.notulen.app.core.minutes.gpu_dispatch import try_dispatch_gpu
from apps.notulen.app.core.minutes.notulen_writer import generate_notulen
from apps.notulen.app.core.minutes.process_job import process_job
from apps.notulen.app.core.minutes.transcribe import transcribe_cpu

__all__ = [
    "generate_notulen",
    "process_job",
    "transcribe_cpu",
    "try_dispatch_gpu",
]
