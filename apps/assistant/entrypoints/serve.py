"""Uvicorn launcher for the assistant container.

Invoked via `python -m apps.assistant.entrypoints.serve` from
the Dockerfile CMD. Binds 0.0.0.0:$OPENCLAW_PORT (default 8000); env
is read at call time inside `main()`.

Also starts the stack-liveness sweep runner, a background daemon
thread (not a separate job: the SQLite state is on a named volume only this
container writes). Started here, in the container's only entrypoint, BEFORE uvicorn so
the sweep is live the moment the server is. The thread is separate from
the event loop, so its blocking checks never block `/health`. It is
deliberately NOT started on `app` import, so the TestClient-based gate
tests don't spin up a live sweep.

FAILURE POLICY: fail-loud. A launcher crash exits non-zero and docker
restarts the container (see the layer seam's docstring). The runner itself is
Tier-2 (a sweep that raises is logged and the loop continues).
"""
from __future__ import annotations

import os

import uvicorn

from apps.assistant.core import state
from apps.assistant.core.knowledge import start_reindexer
from apps.assistant.core.monitor import start_runner
from apps.assistant.core.notify_flush import start_flusher

# Above the idle time a reverse proxy commonly holds a pooled upstream
# connection (Caddy's default is 120 s), so the server is never the side that
# closes one first.
KEEP_ALIVE_SECONDS = 125


def main() -> None:
    # Say out loud, once, which tools cannot run. An unset env var
    # used to surface only as a refusal string mid-conversation, weeks later,
    # indistinguishable from an empty result; now the first boot after it
    # appears carries a WARNING line naming the tool and the missing variable.
    from apps.assistant.core import tools
    from apps.assistant.core.tools.meta import readiness

    readiness.log_table(tools.readiness_table())
    # Write this start into the state volume before anything else can fail.
    # Docker forgets a restart once the container is recreated, so the only
    # place "did the assistant flap last week" can be answered from is the
    # state DB, which survives restarts.
    state.pod_boots.record_boot(os.environ.get("HOSTNAME", "unknown"))
    # Clear the markers of retired beats: a retired beat leaves its
    # `report_marker` row behind, a row no beat can ever advance again. Boot
    # is where that housekeeping goes: idempotent, and the deploy that retires
    # a beat is the deploy that restarts the container.
    state.drop_retired_markers()
    start_runner()
    start_flusher()
    # Keep the knowledge index warm off the request path: an eager build
    # at cold start, then every 30 min, so a chat search never rebuilds inline.
    start_reindexer()
    port = int(os.environ.get("OPENCLAW_PORT", "8000"))
    uvicorn.run(
        "apps.assistant.gates.app:app",
        host="0.0.0.0",
        port=port,
        workers=1,
        log_config=None,
        timeout_keep_alive=KEEP_ALIVE_SECONDS,
    )


if __name__ == "__main__":
    main()
