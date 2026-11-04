"""The tool definitions stay under the prompt budget the assistant pays on every call, and the door tells the model which language each teammate reads.

Every check below is one row of CASES under the one test function; a
row that fails fails the test. The sections below are the notes each
check was written with.

The door tells the model which language each teammate reads, where it writes the message.

WHAT IT PINS. `core/tools/gateway_surface.py`: the `message_teammate`
definition the MCP door serves carries, in its `person` argument, the language
every person in the registry reads. The in-container definition is not changed.

WHY IT EXISTS. A relay drafted in a thread in another language comes out in
that language, and the send refuses it with "not sent: the owner reads
English". The language was known to the container and never shown to the
model at the point it wrote the message.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From the house
rules: Alex reads English, and Robin and Sam read Dutch. The registry below
holds those three people.

The tool door's definitions stay under the prompt budget the assistant pays on every call.

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

import inspect


# From the door tells the model which language each teammate reads where it writes the message.

import pytest


from apps.assistant.core.tools import gateway_surface, write_tools


_PEOPLE = (
    "uuid:alex-uuid=Alex:dev:+15550100001,"
    "uuid:robin-uuid=Robin:legal:+15550100012:nl,"
    "uuid:sam-uuid=Sam:design::nl"
)


def _served(name: str) -> dict:
    return next(
        definition
        for definition in gateway_surface.served_definitions()
        if definition["name"] == name
    )


def _the_served_message_tool_names_each_readers_language(monkeypatch: pytest.MonkeyPatch) -> None:
    """Alex English, Robin and Sam Dutch, in the person argument."""
    monkeypatch.setenv("SIGNAL_PEOPLE", _PEOPLE)
    monkeypatch.delenv(gateway_surface.DOOR_WRITE_ENV, raising=False)
    person = _served(write_tools.MESSAGE_TEAMMATE)["input_schema"]["properties"]["person"]
    for reads in ("Alex reads English", "Robin reads Dutch", "Sam reads Dutch"):
        assert reads in person["description"], person["description"]


def _the_in_pod_definition_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    """Serving the door never rewrites the definition the container's loops hold."""
    monkeypatch.setenv("SIGNAL_PEOPLE", _PEOPLE)
    gateway_surface.served_definitions()
    in_pod = write_tools.definitions([write_tools.MESSAGE_TEAMMATE])[0]
    assert "reads English" not in in_pod["input_schema"]["properties"]["person"]["description"]

# From the tool definitions stay under the prompt budget assistant pays on every call.

import json


#: The door's share of the assistant's 20,000-token fixed prompt, in characters of JSON.
DOOR_BUDGET_CHARS = 22_000


_PEOPLE_2 = (
    "uuid:alex-uuid=Alex:dev:+15550100001,"
    "uuid:robin-uuid=Robin:legal:+15550100012,"
    "uuid:sam-uuid=Sam:dev:+15550100013,"
    "uuid:kim-uuid=Kim:dev:+15550100014"
)


def _the_tool_definitions_stay_under_the_prompt_budget_assistant_pays_on_every_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole served catalogue, writes included, fits the character budget."""
    monkeypatch.setenv("SIGNAL_PEOPLE", _PEOPLE_2)
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


def _cases(scenario, argnames="", argvalues=((),), ids=None, *, marks=(), uses=()):
    """One case per row a check is given; a check given no rows is one case of its fixtures."""
    names = [name.strip() for name in argnames.split(",") if name.strip()] if isinstance(argnames, str) else list(argnames)
    rows = []
    for index, row in enumerate(argvalues):
        row_marks, row_id = (), None
        if isinstance(row, type(pytest.param())):
            row, row_marks, row_id = row.values, row.marks, row.id
        elif len(names) == 1:
            row = (row,)
        if row_id is None and isinstance(ids, (list, tuple)):
            row_id = ids[index]
        label = scenario.__name__.lstrip("_") + (f"-{row_id if row_id is not None else index}" if names else "")
        rows.append(pytest.param(scenario, dict(zip(names, row)), tuple(uses), id=label, marks=(*marks, *row_marks)))
    return rows


CASES = [
    *_cases(_the_served_message_tool_names_each_readers_language),
    *_cases(_the_in_pod_definition_is_left_alone),
    *_cases(_the_tool_definitions_stay_under_the_prompt_budget_assistant_pays_on_every_call),
]


@pytest.mark.parametrize("scenario, given, uses", CASES)
def test_the_tool_definitions_stay_under_the_prompt_budget_and_the_door_names_each_teammates_language(scenario, given, uses, request):
    """The tool definitions stay under the prompt budget the assistant pays on every call, and the door tells the model which language each teammate reads: every row of CASES must hold."""
    for name in uses:
        request.getfixturevalue(name)
    wanted = [name for name, parameter in inspect.signature(scenario).parameters.items()
              if name not in given and parameter.default is parameter.empty]
    scenario(**given, **{name: request.getfixturevalue(name) for name in wanted})
