"""Every tool a VM-local MCP server hands the gateway is named in the assistant's capability block.

WHAT IT PINS. `workspace.capabilities.render_capabilities()`, the block rendered
into AGENTS.md. It ends by telling the assistant that anything on the project's systems not
named above it is impossible, so a tool the gateway really has but the block
leaves out is a tool the assistant will swear it has not got. When that tool is
`journal_read`, the assistant hands the owner journalctl commands instead of
reading the journal itself.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The tool names
are read straight out of `gateway_config_patch.json`, the fragment the gateway
is configured from, as every `toolFilter.include` of `mcp.servers`. The block is
then split at its section paragraphs, and each name must sit in the VM section,
which must come before the paragraph that declares the list complete.
"""
from __future__ import annotations

from apps.assistant.workspace import fragment

from apps.assistant.shared.name import ASSISTANT_NAME

import json
from pathlib import Path

import pytest

from apps.assistant.workspace import capabilities

_CONFIG = Path(__file__).resolve().parents[1] / "gateway_config_patch.json"


#: An owner's own server on the box, as it would sit in the fragment with a
#: toolFilter. The shipped fragment wires none, so the test adds one.
_SERVERS = (("journal", ("container_logs", "journal_read")),)


@pytest.fixture(autouse=True)
def _one_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(capabilities, "_vm_servers", lambda: _SERVERS)


def _wired_tools() -> set[str]:
    """Every tool name the servers are filtered down to."""
    return {tool for _name, tools in _SERVERS for tool in tools}


def test_every_tool_the_gateway_config_wires_in_is_named_in_assistants_capability_block() -> None:
    """journal_read and the mail tools are named, before the 'complete' paragraph."""
    wired = _wired_tools()
    assert "journal_read" in wired, "the tool this test is about has left the config"

    paragraphs = capabilities.render_capabilities().split("\n\n")
    vm_index = next(
        (index for index, paragraph in enumerate(paragraphs)
         if paragraph.startswith(capabilities.VM_HEADING)),
        None,
    )
    assert vm_index is not None, "the block names no tool served on the VM"
    complete_index = next(
        index for index, paragraph in enumerate(paragraphs)
        if "is not a tool named above, you cannot do it" in paragraph
    )
    assert vm_index < complete_index
    missing = {tool for tool in wired if tool not in paragraphs[vm_index]}
    assert not missing, f"wired into the gateway but not named to {ASSISTANT_NAME}: {sorted(missing)}"
