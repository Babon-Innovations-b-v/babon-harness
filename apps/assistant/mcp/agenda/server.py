"""main(), FastMCP stdio transport: assemble the server, register the tools.

Lifecycle: Claude Code spawns this process on session start (`.mcp.json`
names this exact module path, keep `python -m ...server` working), the
first tool call lazily initialises the CalDAV client (``runtime.py``), and
the process stays alive until stdin closes.

Owns transport assembly only; the tool implementations live in ``tools/``
(one per file) and the iCal domain in ``ical/``.

Errors raise ValueError / RuntimeError with operator-facing messages;
the MCP framework serialises them to the client.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .tools import (
    create_event,
    delete_event,
    find_free_slots,
    list_calendars,
    list_events,
    update_event,
)
from .serve import serve

_mcp = FastMCP("agenda")
for _tool in (
    list_calendars,
    list_events,
    find_free_slots,
    create_event,
    update_event,
    delete_event,
):
    _mcp.tool()(_tool)


def main() -> None:
    serve(_mcp)


if __name__ == "__main__":
    main()
