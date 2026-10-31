"""Notulen: automated meeting minutes (dashboard plus GPU worker).

Two runtimes, one package:

    app/          the FastAPI dashboard; see its docstring for the layer map.
                  Built by ``apps/notulen/Dockerfile``.
    entrypoints/  worker.py, the self-contained GPU Kubernetes Job entrypoint
                  (its own image: ``infra/gpu/Dockerfile``).
    shared/       worker_constraints.txt (GPU image dependency pins)
    inputs/       notulen_template.md (shared by both runtimes)
    tests/        the module's tests

The two runtimes deliberately do NOT import each other: the worker image
carries no package code, so its transcription and prompt logic is a declared
twin of ``app/core/minutes``.
"""
