"""Uvicorn launcher, the only thing the container image invokes at runtime.

Module map:
    serve.py  `python -m apps.assistant.entrypoints.serve`
              (Dockerfile CMD); binds 0.0.0.0:$OPENCLAW_PORT

Nothing is re-exported: the entrypoint is addressed by module path,
never imported.

FAILURE POLICY: fail-loud, a launcher crash exits non-zero and k8s
restarts the container; the deadman timer covers prolonged downtime.
"""
from __future__ import annotations

__all__: list[str] = []
