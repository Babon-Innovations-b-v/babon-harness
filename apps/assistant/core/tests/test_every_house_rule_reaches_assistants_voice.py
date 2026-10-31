"""Every rule in `.claude/soul.md` reaches the assistant's voice, and only the two
declared swaps do not.

WHAT IT PINS. `core/voice.py`'s public seam, `render()`, against the house
voice it is rendered from. A paraphrase of `.claude/soul.md` that nothing
compares drifts, and rules such as the em-dash ban go missing. `render()`
reads the file, and this is what stops a copy coming back.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. From
`.claude/soul.md` itself, read here and split on its own bullet markers. The
expected set is every bullet the repository ships, minus exactly two things
this module declares it replaces and says why: the English-only rule, which
The assistant cannot carry because a teammate reads Dutch, and the clause telling the reader
to write a new term into `CONTEXT.md`, which the assistant has no tool for. Nothing in
the expectation is copied from `voice.py`; the file is the authority and the
two swaps are named constants, so a third silent edit fails.
"""
from __future__ import annotations

from apps.assistant.shared.name import ASSISTANT_NAME

import pathlib
import re

from apps.assistant.core import voice

_SOUL = pathlib.Path(__file__).resolve().parents[4] / ".claude" / "soul.md"


def _house_bullets() -> list[str]:
    """The bullets of the house soul, as the repository writes them."""
    return [
        bullet.rstrip()
        for bullet in re.split(r"^- ", _SOUL.read_text(), flags=re.MULTILINE)[1:]
    ]


def test_every_house_rule_reaches_assistants_voice() -> None:
    """Each bullet is in the rendered voice, word for word, except the one
    The assistant replaces."""
    rendered = voice.render()
    missing = []
    for bullet in _house_bullets():
        if bullet.startswith(voice._ENGLISH_ONLY):
            continue
        wanted = " ".join(bullet.replace(voice._GLOSSARY_CLAUSE, "").split())
        if wanted not in " ".join(rendered.split()):
            missing.append(bullet[:60])
    assert not missing, (
        f"the house voice and {ASSISTANT_NAME}'s voice have drifted again; these rules are "
        f"in .claude/soul.md and not in the render: {missing}"
    )


def test_the_two_swaps_are_the_only_ones() -> None:
    """The English-only rule is gone and the assistant's language rule is in its place,
    and the glossary clause the assistant has no tool for does not survive."""
    rendered = voice.render()
    assert voice._ENGLISH_ONLY not in rendered, (
        f"{ASSISTANT_NAME} is being told to write English only, which would send Robin "
        "English"
    )
    assert "in their language" in rendered, "the language rule that replaces it is gone"
    assert "add it to CONTEXT.md" not in rendered, (
        f"{ASSISTANT_NAME} is being told to write a file it has no tool for"
    )


def test_the_soul_still_carries_exactly_one_english_only_rule() -> None:
    """The swap is keyed on that rule's opening words, so a reworded house
    soul must fail here rather than silently sending a teammate English."""
    opens_with_it = [
        bullet for bullet in _house_bullets()
        if bullet.startswith(voice._ENGLISH_ONLY)
    ]
    assert len(opens_with_it) == 1, (
        f".claude/soul.md carries {len(opens_with_it)} rules opening with "
        f"{voice._ENGLISH_ONLY!r}; voice.py swaps exactly one and a person has "
        "to re-decide the swap"
    )
