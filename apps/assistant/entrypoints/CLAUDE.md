# apps/assistant/entrypoints/

`serve.py`, the container's only entrypoint: records the boot, starts the sweep, the flusher and the knowledge reindexer, then runs uvicorn with one worker.

- The background threads start here and never on app import, so tests never run a live sweep.
