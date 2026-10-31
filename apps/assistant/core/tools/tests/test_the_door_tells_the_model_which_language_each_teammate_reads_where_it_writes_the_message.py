"""The door tells the model which language each teammate reads, where it writes the message.

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
"""
from __future__ import annotations

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


def test_the_served_message_tool_names_each_readers_language(monkeypatch: pytest.MonkeyPatch) -> None:
    """Alex English, Robin and Sam Dutch, in the person argument."""
    monkeypatch.setenv("SIGNAL_PEOPLE", _PEOPLE)
    monkeypatch.delenv(gateway_surface.DOOR_WRITE_ENV, raising=False)
    person = _served(write_tools.MESSAGE_TEAMMATE)["input_schema"]["properties"]["person"]
    for reads in ("Alex reads English", "Robin reads Dutch", "Sam reads Dutch"):
        assert reads in person["description"], person["description"]


def test_the_in_pod_definition_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    """Serving the door never rewrites the definition the container's loops hold."""
    monkeypatch.setenv("SIGNAL_PEOPLE", _PEOPLE)
    gateway_surface.served_definitions()
    in_pod = write_tools.definitions([write_tools.MESSAGE_TEAMMATE])[0]
    assert "reads English" not in in_pod["input_schema"]["properties"]["person"]["description"]
