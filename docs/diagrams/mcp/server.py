#!/usr/bin/env python3
"""The diagram MCP server: draw a module the way the diagram set is drawn.

Run as ``python3 docs/diagrams/mcp/server.py`` (``.mcp.json`` names it as
``diagram``, started through ``uv run --group mcp-tools`` so the ``mcp``
library is there). One tool call takes a page's facts (title, legend, boxes
with their popup text, the slides that tell it one step at a time) and its
shape (canvas, placement, regions, edges) and returns a built page: layout,
routing, label fitting, validation and the popup wiring are all handled here.

The files beside this one, one concern each, imported flat because this
directory is a set of scripts and not a package:

- ``runtime.py``        where the repository keeps specs, sidecars, pages and
                        the build tooling, and the one subprocess helper
- ``page_faults.py``    every mechanical reason a page would embarrass its author
- ``bible_debt.py``     the sentences the bible still owes a page
- ``group_echoes.py``   which pages have become a redraw of their group page
- ``page_freshness.py`` which pages the code moved out from under
- ``draw_module.py``, ``link_module.py``, ``check_diagrams.py``: the three tools

Every verdict about the set is deferred to ``docs/diagrams/tools/linkmap.py``.

TRANSPORT. stdio by default, which is what Claude Code spawns. A network
transport is asked for explicitly, with ``--transport sse|streamable-http`` and
``--port`` (or ``DIAGRAM_MCP_TRANSPORT``/``DIAGRAM_MCP_HOST``/
``DIAGRAM_MCP_PORT``), and binds loopback unless told otherwise, because
nothing here checks who is calling.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

_TRANSPORTS = ("stdio", "sse", "streamable-http")
_DEFAULT_HOST = "127.0.0.1"


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="the diagram MCP server")
    parser.add_argument("--transport", choices=_TRANSPORTS,
                        default=os.environ.get("DIAGRAM_MCP_TRANSPORT", "stdio"))
    parser.add_argument("--host", default=os.environ.get("DIAGRAM_MCP_HOST", _DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=_port_from_env())
    return parser.parse_args(argv)


def _port_from_env() -> int | None:
    raw = os.environ.get("DIAGRAM_MCP_PORT")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        raise SystemExit(f"DIAGRAM_MCP_PORT is not a number: {raw!r}")


def _is_loopback(host: str) -> bool:
    return host in ("127.0.0.1", "localhost", "::1", "[::1]")


def _allow_the_address_we_bound(settings, host: str, port: int) -> None:
    """Let the address we are listening on through the rebinding check.

    The library accepts a ``Host`` header only for loopback, so binding anywhere
    else answers every request 421 with nothing in the log saying why. The
    exact address bound is added and nothing else, so the protection stays on.
    """
    security = getattr(settings, "transport_security", None)
    if security is None or _is_loopback(host):
        return
    for name in (f"{host}:{port}", host):
        if name not in security.allowed_hosts:
            security.allowed_hosts.append(name)
    for origin in (f"http://{host}:{port}", f"https://{host}:{port}"):
        if origin not in security.allowed_origins:
            security.allowed_origins.append(origin)


def build():
    """The FastMCP server with the three tools registered."""
    from mcp.server.fastmcp import FastMCP

    from check_diagrams import check_diagrams
    from draw_module import draw_module
    from link_module import link_module

    server = FastMCP("diagram")
    for tool in (draw_module, link_module, check_diagrams):
        server.tool()(tool)
    return server


def main(argv: list[str] | None = None) -> None:
    args = _parse(argv)
    server = build()
    if args.transport == "stdio":
        server.run()
        return
    if args.port is None:
        raise SystemExit(f"--port is required for the {args.transport} transport "
                         "(or set DIAGRAM_MCP_PORT); there is no default, because two "
                         "servers on one port fail in ways that look like a broken tool")
    server.settings.host = args.host
    server.settings.port = args.port
    _allow_the_address_we_bound(server.settings, args.host, args.port)
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
