"""The agenda server registers every tool the tools package exports, and nothing else.

WHAT IT PINS. How the MCP servers under `apps/assistant/mcp` are put together:
`agenda/server.py` assembles the FastMCP instance from the callables in
`agenda/tools`, and a callable left out of that registration is a calendar verb
the assistant can never reach, while the tests, which call the tools directly,
stay green. The server is imported and asked for its tool list the way an MCP
client asks; no transport is started and no calendar is contacted.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The six calendar
verbs are named here by hand, one case each, from the tools package's module
map: list calendars, list events, find free slots, create, update and delete an
event. The last case says the server offers no name outside those six.

ONE FUNCTION. This group's one test. A new check is a parametrized case of
it, never a second function.

WHAT IT WAS PROVED AGAINST. The break in this test's register row leaves
`delete_event` out of the registration, so the delete case fails.

GUARDS. One test per module group (#1210), 2026-11-05.
"""
from __future__ import annotations

import asyncio
import importlib

import pytest

VERBS = ("list_calendars", "list_events", "find_free_slots", "create_event", "update_event", "delete_event")

CASES = [pytest.param(verb, id=verb) for verb in VERBS] + [pytest.param(None, id="nothing-else")]


@pytest.mark.parametrize("verb", CASES)
def test_the_agenda_server_registers_every_tool_the_tools_package_exports_and_nothing_else(verb: str | None) -> None:
    """The verb is offered to an MCP client, and the server offers no other."""
    server = importlib.import_module("apps.assistant.mcp.agenda.server")
    offered = [tool.name for tool in asyncio.run(server._mcp.list_tools())]
    if verb is None:
        assert sorted(set(offered) - set(VERBS)) == []
    else:
        assert verb in offered
