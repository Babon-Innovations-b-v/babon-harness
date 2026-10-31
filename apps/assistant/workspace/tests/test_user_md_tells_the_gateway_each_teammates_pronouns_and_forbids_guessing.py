"""USER.md forbids the gateway to guess any teammate's pronouns.

WHAT IT PINS. `workspace.user.render_user()`, the USER.md the gateway reads on
every turn, through `core.people.pronoun_directive`. A name does not say
which pronoun a person uses, and a model that is told nothing guesses from the
name and gets it wrong in front of the person.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The registry
carries no pronouns, so every block must tell the model to use the person's
name or neutral wording, and no block may offer a he/him or she/her form to
copy.
"""
from __future__ import annotations

import pytest

from apps.assistant.core import state
from apps.assistant.workspace import user

_PEOPLE = (
    "uuid:aaa=Alex:founder:+15550100012,"
    "uuid:bbb=Robin:legal::nl,"
    "uuid:ccc=Kim:design"
)


@pytest.fixture()
def blocks(monkeypatch) -> dict[str, str]:
    """USER.md split into its per-person blocks, keyed by name."""
    monkeypatch.setenv("SIGNAL_PEOPLE", _PEOPLE)
    monkeypatch.setattr(state, "list_person_rules", lambda name: [])
    rendered = user.render_user()
    found: dict[str, str] = {}
    for chunk in rendered.split("### ")[1:]:
        name, _, body = chunk.partition("\n")
        found[name.strip()] = body
    return found


@pytest.mark.parametrize("name", ["Alex", "Robin", "Kim"])
def test_every_teammate_is_named_rather_than_guessed(blocks, name) -> None:
    block = blocks[name]
    assert "use their name or neutral wording" in block, block
    assert "he/him" not in block and "she/her" not in block, block


def test_a_reader_of_another_language_is_written_to_in_it(blocks) -> None:
    assert "'nl'" in blocks["Robin"], blocks["Robin"]
