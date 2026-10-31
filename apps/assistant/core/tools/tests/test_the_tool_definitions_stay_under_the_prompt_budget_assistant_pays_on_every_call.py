"""The tool door's definitions stay under the prompt budget the assistant pays on every call.

WHAT IT PINS. `core/tools/gateway_surface.served_definitions()`, the catalogue
the MCP door hands the gateway, read and write halves together, measured as the
JSON the model is sent.

WHY IT EXISTS. Every model call the gateway makes for the assistant carries every definition
in full before the first word of conversation, so unbounded definitions can
become a large share of a fixed prompt and make every call expensive. The fixed prompt is kept below
20,000 tokens; the door's share of that is the budget here.
A description is for what the model must know to call the tool: what it does,
the arguments, the refusals that matter. Guidance prose belongs in the code's
refusals, the overlays, or the assistant's bible, which it searches.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The budget is
a number fixed from the measurement above: 20,000 tokens of fixed prompt, of
which the door may take about 8,500, at the measured 2.55 characters per token
of these definitions (23,596 characters counted as 9,243 tokens by Anthropic's
count_tokens), which is 22,000 characters. The registry holds
four people so the language line the door adds to `message_teammate` counts.
"""
from __future__ import annotations

import json

import pytest

from apps.assistant.core.tools import gateway_surface

#: The door's share of the assistant's 20,000-token fixed prompt, in characters of JSON.
DOOR_BUDGET_CHARS = 22_000

_PEOPLE = (
    "uuid:alex-uuid=Alex:dev:+15550100001,"
    "uuid:robin-uuid=Robin:legal:+15550100012,"
    "uuid:sam-uuid=Sam:dev:+15550100013,"
    "uuid:kim-uuid=Kim:dev:+15550100014"
)


def test_the_tool_definitions_stay_under_the_prompt_budget_assistant_pays_on_every_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole served catalogue, writes included, fits the character budget."""
    monkeypatch.setenv("SIGNAL_PEOPLE", _PEOPLE)
    monkeypatch.delenv(gateway_surface.DOOR_WRITE_ENV, raising=False)
    served = gateway_surface.served_definitions()
    assert gateway_surface.write_definitions(), "the write half is not being measured"
    sizes = sorted(
        ((len(json.dumps(definition)), definition["name"]) for definition in served),
        reverse=True,
    )
    total = sum(size for size, _ in sizes)
    assert total <= DOOR_BUDGET_CHARS, (
        f"the door's definitions are {total} characters against a budget of "
        f"{DOOR_BUDGET_CHARS}; largest: {sizes[:5]}"
    )
