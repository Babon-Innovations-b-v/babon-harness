"""Entrypoints for notulen runtimes that ship as their own image.

``worker.py`` is the GPU Kubernetes Job entrypoint (pyannote, whisper-large-v3,
Claude). The dashboard's entrypoint is ``app/entrypoints/main.py``.
"""
