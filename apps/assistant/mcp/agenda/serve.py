"""serve(): run an MCP server on the transport asked for.

Defaults to stdio, which is how a Claude session spawns it. A network
transport is asked for explicitly, on the command line or in the environment
(AGENDA_MCP_TRANSPORT, AGENDA_MCP_HOST, AGENDA_MCP_PORT), and binds loopback
unless told otherwise, because the server reads calendars and authenticates
no caller.
"""
from __future__ import annotations

import argparse
import os

_TRANSPORTS = ("stdio", "sse", "streamable-http")
_DEFAULT_HOST = "127.0.0.1"


def serve(mcp, argv: list[str] | None = None) -> None:
    """Run `mcp` on the transport named by argv or the environment."""
    args = _parse(argv)
    if args.transport == "stdio":
        mcp.run()
        return
    if args.port is None:
        raise SystemExit(
            f"--port is required for the {args.transport} transport "
            "(or set AGENDA_MCP_PORT); there is no default"
        )
    mcp.settings.host = args.host
    mcp.settings.port = args.port
    _allow_the_address_we_bound(mcp.settings, args.host, args.port)
    mcp.run(transport=args.transport)


def _allow_the_address_we_bound(settings, host: str, port: int) -> None:
    """Let the bound address through the library's DNS-rebinding check, and
    nothing else: a request under any other name is still refused."""
    security = getattr(settings, "transport_security", None)
    if security is None or host in ("127.0.0.1", "localhost", "::1", "[::1]"):
        return
    for name in (f"{host}:{port}", host):
        if name not in security.allowed_hosts:
            security.allowed_hosts.append(name)
    for origin in (f"http://{host}:{port}", f"https://{host}:{port}"):
        if origin not in security.allowed_origins:
            security.allowed_origins.append(origin)


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--transport", choices=_TRANSPORTS,
                        default=os.environ.get("AGENDA_MCP_TRANSPORT", "stdio"))
    parser.add_argument("--host", default=os.environ.get("AGENDA_MCP_HOST", _DEFAULT_HOST))
    raw_port = os.environ.get("AGENDA_MCP_PORT")
    parser.add_argument("--port", type=int, default=int(raw_port) if raw_port else None)
    return parser.parse_args(argv)
