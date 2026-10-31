"""Notulen dashboard: FastAPI app package.

A five-layer module: ``entrypoints/`` (FastAPI app and routes), ``gates/``
(upload validation), ``core/`` (minutes, publish, sessions, board),
``shared/`` (config, identity, S3, notulen_jobs DB helpers), ``inputs/``
(the SPA: dashboard.html and dashboard.js).

The GPU worker entrypoint is NOT here: it ships as its own image from
``apps/notulen/entrypoints/worker.py``.
"""
