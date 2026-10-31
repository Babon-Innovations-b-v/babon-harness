"""USER.md: who the assistant is talking to, and how each of them reads.

The container picks ONE person's block per call: `core.people.render(sender)` resolves
the sender to a teammate and pastes that teammate's style and their own rules,
so the choice is deterministic and made before the model sees anything. A
workspace bootstrap file cannot do that. There is one workspace, one USER.md,
and it holds the whole registry, so the model reads the whole people table and
picks a row itself.

That is a real downgrade and it is priced rather than hidden. A language
paragraph sitting in the prompt is not enough on its own: a model still
answers people in the wrong language, and the fix for that is a
deterministic seam, not better prose. So the language each person reads is
stated here as its own flat sentence per person, taken from
`core.people.language_for`, which is the same table `core.claims.wrong_language`
checks a draft against at the send seams that remain ours.

The format is upstream's own, read off the stub OpenClaw ships in the
workspace: an HTML metadata comment above each block, and every entry
opening with an imperative. Upstream's own field there is `observed:` with the
date the fact was observed; nothing here is observed, so the field says where
the block came from instead (`_BLOCK_SOURCE`), and the one real date, when a
person set one of their own rules, is rendered on that rule.

Public callables: `render_user()`.

FAILURE POLICY: Tier-1 fail-loud. `state.list_person_rules` is a Tier-1 state
read; a failure there propagates and nothing is written, because a USER.md
silently missing a person's rules is the assistant that has forgotten what they asked
for. The registry parse never raises, so an empty registry is refused here by
hand: see `EmptyRegistry`.
"""
from __future__ import annotations

from apps.assistant.shared.name import ASSISTANT_NAME

import re

from apps.assistant.core import people, state

#: The opening label `core.people`'s style blocks carry, "Style for them:" or
#: "Style for a teammate:". Removed here and nowhere else.
_STYLE_LABEL = re.compile(r"^Style for [^:]+:\s*")

#: How a language code from `people.language_for` reads in a sentence. A code
#: that is in neither this map nor the registry is reported as undeclared, and
#: never guessed: "not declared" is not "English" (`people.language_for`).
_LANGUAGE_NAMES = {"en": "English", "nl": "Dutch"}

#: The metadata comment above each block. Upstream's stub puts `observed:` and
#: a date there, meaning the day the fact was observed. No date here would be
#: true: the registry is configuration, and a render date stamped as `observed`
#: would both state a falsehood about the file's own provenance and rewrite
#: every block at local midnight for no change in content. So the field says
#: where the block came from, and the dates that are real ride their own rules.
_BLOCK_SOURCE = "<!-- source: the people registry | status: active -->"

_HEADING = f"""# USER.md

Rendered from the repository every deploy; an edit here does not survive. A teammate changes their own entry by telling {ASSISTANT_NAME}, which
records it as a personal rule.

Every person below is somebody you may talk to. Read the block for the person
you are actually talking to, and no other block."""


class EmptyRegistry(RuntimeError):
    """`SIGNAL_PEOPLE` names nobody, so there is no USER.md worth writing."""


def render_user() -> str:
    """The rendered USER.md: one directive block per teammate in the registry,
    in registry order, each carrying the language they read, how to refer to
    them, the house style for them, and their own rules.

    Raises `EmptyRegistry` when the registry names nobody. An empty registry
    otherwise renders a heading and an empty `## Directives` section, which is a
    non-empty file: it would pass a caller's "did anything come back" check and
    replace a good USER.md with one holding no reader profile at all.
    `SIGNAL_PEOPLE` reaches the container through a secret the deployment marks
    optional, so an absent value is a state the manifest contemplates, and this
    is the guard for it.
    """
    names = people.names()
    if not names:
        raise EmptyRegistry(
            "SIGNAL_PEOPLE names nobody, so USER.md would carry no reader "
            "profile at all. Refusing to render rather than blanking the "
            "profiles the gateway already holds."
        )
    blocks = [_HEADING, "## Directives"]
    for name in names:
        blocks.append(_block_for(name))
    return "\n\n".join(blocks)


def _block_for(name: str) -> str:
    """One person's directive block: heading, metadata line, then the
    directives, most binding last so a personal rule reads as the override it
    is."""
    lines = [f"### {name}", _BLOCK_SOURCE, ""]
    lines.append(f"- {_language_directive(name)}")
    lines.append(f"- {people.pronoun_directive(name)}")
    lines.append(f"- Always talk to {name} this way: {_style_body(name)}")
    for rule in state.list_person_rules(name):
        lines.append(
            f"- Always honour {name}'s own rule, which they set{_set_on(rule)} "
            f"and can change: {rule['text']}"
        )
    return "\n".join(lines)


def _set_on(rule: dict) -> str:
    """When a personal rule was set, as a clause, or nothing when the row does
    not say. The date is the row's own `added_at` and never today's: a rule set
    in July stays a rule set in July however often this file is rendered."""
    added = str(rule.get("added_at") or "")
    return f" on {added[:10]}" if len(added) >= 10 else ""


def _style_body(name: str) -> str:
    """The style block without its own opening label.

    `people.style_for` returns a block written for a prompt that already says
    whose block it is, so it opens "Style for them:" or "Style for a teammate:". Here
    the directive already names the person, and the two labels back to back read
    like a bug. Only the label is removed; the advice itself is never reworded,
    because a second copy of it would drift from the registry.
    """
    return _STYLE_LABEL.sub("", people.style_for(name), count=1)


def _language_directive(name: str) -> str:
    """The one sentence saying which language this person reads, or saying
    plainly that nothing declares it."""
    code = people.language_for(name)
    language = _LANGUAGE_NAMES.get(code or "")
    if not language:
        return (
            f"Ask {name} which language they would rather read; the registry "
            "does not say, so do not assume one."
        )
    return f"Always write to {name} in {language}."
