"""Who the assistant is talking to: the people registry.

The allowlist says WHO may chat; this module says who they ARE. The
`SIGNAL_PEOPLE` setting (comma-separated `<key>=Name:role[:+E164[:language]]`,
kept in the vault next to `SIGNAL_ALLOWLIST`) maps a sender key (a number, or
`uuid:<id>`) to a name, a free-text role, optionally a Signal number the
assistant can send TO, and optionally the language they read (an ISO code,
default `en`). Leave the number empty to give a language without one:
`uuid:abc=Sam:design::nl`.

`render(sender)` returns the WHO-YOU-ARE-TALKING-TO block the chat prompt
carries. `number_for(name)` resolves a teammate's send number so the
assistant can message them, and `language_for(name)` answers which language
they read, so a deterministic send seam can check a draft without asking the
model.

The optional third field is the SEND target: admission still matches on the
key, but signal-cli sends to a phone number, so a teammate the assistant
should be able to message carries their `+E164` here. It is also the WEAK
identity, and it is reachable only through `identify_by_number`: the timer
beats look people up by number with no UUID in hand. `identify` never
consults it, so a chat sender whose UUID matches nobody can never inherit a
teammate's profile and language from a reassignable number.

Roles are free text and carry no code: the role is shown to the model as a
hint about the reader, and the tone comes from the language and from the
person's own rules (`personal_rule`).

Public callables: `identify(sender)`, `identify_by_number(number)`,
`render(sender)`, `style_for(name)`, `number_for(name)`, `language_for(name)`,
`pronoun_directive(name)`, `names()` and `with_send_numbers()`.

FAILURE POLICY: pure env parse. Malformed entries are skipped with a log line
(a typo in one entry must not unperson everyone else); an unknown sender
renders a generic block, never an error.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from apps.assistant.gates.e164 import normalize_number

log = logging.getLogger("openclaw.people")

_PEOPLE_ENV = "SIGNAL_PEOPLE"

_DEFAULT_LANGUAGE = "en"

_DEFAULT_STYLE = (
    "Style for them: plain everyday language, explain technical terms "
    "briefly, lead with the answer, stay warm and helpful."
)


@dataclass(frozen=True)
class Person:
    name: str
    role: str
    language: str = _DEFAULT_LANGUAGE


def identify(sender: str, sender_uuid: str | None = None) -> Person | None:
    """Look the sender up in `SIGNAL_PEOPLE`, matching by number OR Signal
    UUID. An entry's key is a number, or `uuid:<id>` for the stronger
    non-reassignable identity. None when unmapped (still allowlisted, the
    gate decided admission, not us).

    The KEY match is the ONLY match here, because this is the
    admission-adjacent lookup the chat loop uses and a phone number is
    reassignable. The registry's optional SEND number is deliberately
    NOT a fallback: a chat sender whose UUID matches no key would otherwise
    adopt the profile, style rules and language of whoever carries that
    number. A caller that holds a number and no UUID (every timer beat) asks
    `identify_by_number` instead.
    """
    raw = os.environ.get(_PEOPLE_ENV, "")
    want_uuid = (sender_uuid or "").strip().lower()
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        key, _, profile = entry.partition("=")
        name, role, _number, language = _parse_profile(profile)
        if not name:
            log.warning("SIGNAL_PEOPLE entry %r malformed; skipped", entry)
            continue
        key = key.strip()
        if key.lower().startswith("uuid:"):
            matched = bool(want_uuid) and key[len("uuid:"):].strip().lower() == want_uuid
        else:
            matched = normalize_number(key) == normalize_number(sender)
        if matched:
            return Person(name=name, role=role, language=language)
    return None


def identify_by_number(number: str) -> Person | None:
    """The person a phone NUMBER belongs to: the entry keyed by that number,
    or failing that the one carrying it as a SEND number. None when neither.

    This is the lookup the timer beats need. They know a number and no UUID,
    so against a uuid-keyed registry `identify` answers nobody for every one
    of them, and everyone would lose their language and personal rules on
    every beat. It is a separate callable on purpose: a number is
    reassignable, so the chat path, which holds a real sender UUID, must never
    fall through to one.
    """
    return identify(number) or _by_send_number(number)


def _by_send_number(sender: str) -> Person | None:
    """The person whose SEND number is `sender`, or None. The weak half of
    `identify_by_number`, never reachable from `identify`."""
    wanted = normalize_number(sender or "")
    if not wanted:
        return None
    for entry in os.environ.get(_PEOPLE_ENV, "").split(","):
        entry = entry.strip()
        if not entry or "=" not in entry:
            continue
        _key, _, profile = entry.partition("=")
        name, role, number, language = _parse_profile(profile)
        if name and number and normalize_number(number) == wanted:
            return Person(name=name, role=role, language=language)
    return None


def _parse_profile(profile: str) -> tuple[str, str, str | None, str]:
    """`Name:role[:+E164[:language]]` -> (name, role, send_number, language).

    Missing fields come back empty or None; the number is kept only if it
    looks like an E.164 (`+` prefix), so a two-field entry never mistakes the
    role for a number. The language defaults to English."""
    parts = profile.split(":")
    name = parts[0].strip() if parts else ""
    role = parts[1].strip() if len(parts) > 1 else ""
    number = parts[2].strip() if len(parts) > 2 and parts[2].strip().startswith("+") else None
    language = parts[3].strip().lower() if len(parts) > 3 and parts[3].strip() else _DEFAULT_LANGUAGE
    return name, role, number, language


def number_for(name: str) -> str | None:
    """The Signal send number for a teammate by name (case-insensitive),
    from `SIGNAL_PEOPLE`'s optional third field. None when the person is
    unknown or carries no send number (the assistant then cannot message them and
    should say so)."""
    want = name.strip().lower()
    if not want:
        return None
    for entry in os.environ.get(_PEOPLE_ENV, "").split(","):
        entry = entry.strip()
        if not entry or "=" not in entry:
            continue
        _key, _, profile = entry.partition("=")
        entry_name, _role, number, _language = _parse_profile(profile)
        if entry_name and entry_name.lower() == want:
            return number
    return None


def language_for(name: str) -> str | None:
    """Which language a teammate reads, as an ISO code, or None when the
    registry does not carry this name (case-insensitive).

    None means "not a known person", never "English": a caller must decide for
    itself what to do with an unknown reader rather than be handed a guess. A
    known person without a fourth field reads English.
    """
    person = _profile_by_name(name)
    return None if person is None else person.language


def pronoun_directive(name: str) -> str:
    """One sentence saying how to refer to this teammate, for every prompt and
    workspace block that describes them. The registry carries no pronouns, so
    the sentence forbids a guess: silence is what lets a model guess from a
    name, and a name does not say it."""
    return (
        f"The registry does not give {name}'s pronouns: use their name or "
        "neutral wording, never guess he or she."
    )


def style_for(name: str) -> str:
    """The house style block for a teammate BY NAME (case-insensitive).

    Same tables and same precedence as the block `render` builds: the
    per-person entry replaces the per-role one, and a person nobody has an
    entry for gets the neutral default. A name the registry does not carry also
    gets the default, because a style is advice about how to write and there is
    no harm in the plain one; that is not true of `language_for`, which answers
    None rather than guess.

    It exists so a second reader can have the same table: the
    workspace generator walks `names()` and needs the block per person, while
    `render` holds a resolved `Person`. Both come through `_style_of`, so there
    is one precedence rule and not two.
    """
    person = _profile_by_name(name)
    if person is None:
        return _DEFAULT_STYLE
    return _style_of(person)


def _style_of(person: Person) -> str:
    """This person's style block: the plain default plus the language they
    read when it is not English. Their own rules (`personal_rule`) are
    layered on top by `_rules_block`."""
    if person.language and person.language != _DEFAULT_LANGUAGE:
        return f"{_DEFAULT_STYLE} Write to them in the language with code '{person.language}'."
    return _DEFAULT_STYLE


def _profile_by_name(name: str) -> Person | None:
    """The registry entry for a teammate by name (case-insensitive), or None."""
    want = name.strip().lower()
    if not want:
        return None
    for entry in os.environ.get(_PEOPLE_ENV, "").split(","):
        entry = entry.strip()
        if not entry or "=" not in entry:
            continue
        _key, _, profile = entry.partition("=")
        entry_name, role, _number, language = _parse_profile(profile)
        if entry_name and entry_name.lower() == want:
            return Person(name=entry_name, role=role, language=language)
    return None


def names() -> list[str]:
    """Every teammate in `SIGNAL_PEOPLE`, in registry order, de-duplicated by
    name. The away block walks these so a person with no send number (a teammate
    today) is still reported on."""
    seen: set[str] = set()
    found: list[str] = []
    for entry in os.environ.get(_PEOPLE_ENV, "").split(","):
        entry = entry.strip()
        if not entry or "=" not in entry:
            continue
        _key, _, profile = entry.partition("=")
        name, _role, _number, _language = _parse_profile(profile)
        if name and name.lower() not in seen:
            seen.add(name.lower())
            found.append(name)
    return found


def with_send_numbers() -> list[tuple[str, str]]:
    """Every teammate in `SIGNAL_PEOPLE` who carries a send number, as
    (name, +E164) pairs, de-duplicated by number. The meeting reminder
    walks these to know who to remind about an upcoming call on
    their calendar. Empty when nobody has a send number."""
    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    for entry in os.environ.get(_PEOPLE_ENV, "").split(","):
        entry = entry.strip()
        if not entry or "=" not in entry:
            continue
        _key, _, profile = entry.partition("=")
        name, _role, number, _language = _parse_profile(profile)
        if name and number and number not in seen:
            seen.add(number)
            result.append((name, number))
    return result


def _audience(sender: str, sender_uuid: str | None) -> Person | None:
    """Who the block `render` builds is about, or None.

    A caller holding a UUID holds the strong identity: when it matches no key
    the answer is nobody, and a reassignable send number must not talk it into
    A teammate's profile. That is the chat loop, every time. A caller
    holding no UUID has only a number, which is the timer beats: their
    audience is the page recipient from `outbound.recipient()`, an
    operator-set number, and resolving it is what gives the beats the reader's
    style and personal rules at all.
    """
    if sender_uuid:
        return identify(sender, sender_uuid)
    return identify_by_number(sender)


def render(sender: str, sender_uuid: str | None = None) -> str:
    """The WHO-YOU-ARE-TALKING-TO block for the chat prompt."""
    person = _audience(sender, sender_uuid)
    if person is None:
        return (
            "WHO YOU ARE TALKING TO, an allowlisted teammate you have no "
            "profile for. Use plain everyday language, explain technical "
            "terms briefly, and ask their name so the owner can add them to your "
            "people registry."
        )
    style = _style_of(person)
    return (
        f"WHO YOU ARE TALKING TO, {person.name} ({person.role or 'teammate'}). "
        f"{pronoun_directive(person.name)} "
        f"{style} Address them by name when it is natural; their history "
        "with you is the conversation above, and your journal notes tagged "
        f"(about {person.name}) are about them."
    ) + _rules_block(person.name)


def _rules_block(name: str) -> str:
    """This person's OWN rules (they set them, they can change them), applied
    only when the assistant talks to them. Layered on top of the role style, so a
    personal rule wins when it conflicts. Empty when they have set none."""
    from apps.assistant.core import state  # lazy: avoid core-init cycle
    rules = state.list_person_rules(name)
    if not rules:
        return ""
    lines = "\n".join(f"- {rule['text']}" for rule in rules)
    return (
        f"\n\nHOW {name.upper()} WANTS YOU TO TALK TO THEM, their own rules, "
        f"which they set and can change, and which apply ONLY when you talk to "
        f"{name}. Where one of these conflicts with your general style, theirs "
        f"wins:\n{lines}"
    )
