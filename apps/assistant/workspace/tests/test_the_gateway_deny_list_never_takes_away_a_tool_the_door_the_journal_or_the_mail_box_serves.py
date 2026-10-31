"""The gateway deny list never takes away a tool the door, the journal or the mail box serves.

WHAT IT PINS. `workspace/gateway_config_patch.json`'s `tools.deny`, the list
step 68 hands the gateway to switch off upstream tools the assistant does not use, checked against the tools the assistant must keep: every tool the
MCP door serves (`core/tools/gateway_surface.served_definitions()`), every tool
the fragment wires in from a VM-local server (`toolFilter.include`), and the
upstream tools its memory and workspace run on.

WHY IT EXISTS. Upstream's deny is case-insensitive and takes `*` wildcards,
and it applies to MCP tools as well as its own. One careless glob there
(`assistant*`, `*__*`) would leave the assistant with no door at all on the next deploy,
and nothing else would say so: the gateway would answer every question with
"I cannot reach that".

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The gateway
names an MCP tool `<server>__<tool>`, read off the tool list in a live run's
system prompt (`assistant-tools__stack_status`,
`harness-journal__journal_read`). The kept upstream tools are the ones the
assistant actually uses: `write` for
its memory file, `memory_search`, `memory_get`, `exec`, `web_search`.
"""
from __future__ import annotations

from apps.assistant.workspace import fragment

from apps.assistant.shared.name import ASSISTANT_NAME

import fnmatch
import json
from pathlib import Path

import pytest

from apps.assistant.core.tools import gateway_surface

_FRAGMENT = Path(__file__).resolve().parents[1] / "gateway_config_patch.json"
_DOOR_SERVER = "assistant-tools"
_KEPT_UPSTREAM = ("read", "write", "edit", "exec", "memory_search", "memory_get", "web_search")


def _fragment() -> dict:
    """The fragment as step 68 sends it."""
    return fragment.render_config_patch()


def _kept_tools() -> set[str]:
    """Every tool name, as the gateway spells it, that the assistant must keep."""
    door = {
        f"{_DOOR_SERVER}__{definition['name']}"
        for definition in gateway_surface.served_definitions()
    }
    vm_local = {
        f"{server}__{tool}"
        for server, spec in _fragment()["mcp"]["servers"].items()
        for tool in spec.get("toolFilter", {}).get("include", [])
    }
    return door | vm_local | set(_KEPT_UPSTREAM)


def test_the_gateway_deny_list_never_takes_away_a_tool_the_door_the_journal_or_the_mail_box_serves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No deny pattern matches a door, journal, mail or memory tool."""
    monkeypatch.delenv(gateway_surface.DOOR_WRITE_ENV, raising=False)
    deny = [pattern.lower() for pattern in _fragment()["tools"]["deny"]]
    assert deny, "the fragment denies nothing, so this test checks nothing"
    kept = _kept_tools()
    denied = sorted(
        tool for tool in kept
        if any(fnmatch.fnmatchcase(tool.lower(), pattern) for pattern in deny)
    )
    assert not denied, f"the deny list takes these away from {ASSISTANT_NAME}: {denied}"
