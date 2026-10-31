"""What the MCP door serves the gateway, decided in one place.

Two callers need the same answer to one question. The door in `gates/mcp.py` builds its catalogue, and the capability
block in `workspace/capabilities.py` tells the assistant what it has; both called
`core.tools.investigation_definitions()` would be fine only while the answer
is "the read-only tools and nothing else". With the write tools served the
answer has two halves, and two modules computing it separately is two chances
for the prompt to describe a door that is not there. When the block says
nothing specific, the assistant believes the doctrine instead and may tell the
team it can book meetings it has no tool for, or the reverse.

So this module is the single answer. `served_definitions()` is the catalogue,
read half then write half, and both callers take it verbatim.

THE WRITE HALF CARRIES AN ARGUMENT THE POD'S OWN LOOPS DO NOT NEED. Inside the
pod a write tool is dispatched with an `Actor` the loop already holds: the chat
loop knows who is talking because a Signal message carries a verified sender.
The door has one bearer and one caller, so an MCP call carries no requester at
all, while `github_act` takes a board write only from someone the people
registry holds and every audit row is supposed to say who asked. A fixed actor
would stamp every write with one person's name. So
every write tool served here gains one required argument, `requested_by`, and
the door resolves it against the people registry before anything is dispatched
(`gates/mcp.py` owns that resolution and explains it).

THE DECISION, tool by tool, because the house rules ask for one. Five of the nine
change something outside the assistant (the team calendar, a video call, a Signal message,
the GitHub board, the bible) and each already wears the two locks in
`write_guard.py`: a kill switch and an audit row. Four of them write only
The assistant's own SQLite (`manage_worklist`, `remember_note`, `remember_principle`,
`personal_rule`) and the house rules left those ungated on purpose, because the only
way to reach them was a Signal message from a verified sender. The door has no
verified sender, so that reason does not travel with them, and two of the four
are the ones that rewrite the assistant's own instructions: `remember_principle` writes
global doctrine into every in-container loop's prompt, and `personal_rule` changes
how the assistant talks to one named person. They are served because recording a correction through
the door is part of what it is for, and the door pays for the guarantee it
took away: it records EVERY door-driven write in `state.assistant_actions` before
dispatching it, including the four that record nothing themselves, and
`ASSISTANT_DOOR_WRITE=0` turns the whole write half off in one restart.

A tenth, added later:
`record_answer`, which the chat session calls when a teammate's message
answers an open worklist item. It writes only the assistant's own SQLite (the answer
on the row, the answered stamp in the told ledger), refuses an unknown or
closed item, an empty answer and an answerer the registry does not hold, and
is not one the assistant may book to itself. It exists because a reply lands only in
the gateway's chat session and nothing else could carry it to the brief.

That switch is an OFF lever and not an arming one, which is why an unset value
means on. The per-tool switches live in the container secret; a fail-closed
default here would ship a door that is silently read-only and an assistant
that tells the team it cannot act.

What it does NOT own: the tools, their schemas and their locks, which are
`core/tools/`'s and are copied verbatim apart from the added argument; the
audit row and the identity check, which are `gates/mcp.py`'s; who may hold the
bearer, which is `shared/auth.py`'s; and the protocol, which is
`gates/mcp.py`'s.

Public callables: `read_definitions()`, `write_definitions()`,
`served_definitions()`, `is_served_write_tool()`, `door_writes_enabled()`.

FAILURE POLICY: pure data. It reads two registries and copies dicts, so there
is no IO to fail; a definition it cannot find is a KeyError at import-adjacent
call time rather than a silently shorter catalogue, because a catalogue that
quietly loses a tool is how the assistant starts saying it cannot do things it can.
"""
from __future__ import annotations

from apps.assistant.shared.name import ASSISTANT_NAME

import copy
import os
from typing import Any

from apps.assistant.core import people, tools
from apps.assistant.core.tools import write_tools

#: The argument every write tool gains at the door: who asked for this write.
#: Named as data rather than typed as a literal in three files, because the
#: door strips it, the schema declares it and the capability block tells the assistant
#: to fill it, and those three must be the same word.
REQUESTER_ARGUMENT = "requested_by"

#: The one lever that takes the write half of the door away again. Set it to
#: "0" in the container secret and the door serves the read tools only: the writes
#: are not listed, a call to one is refused, and the capability block moves all
#: nine into the section that tells the assistant it cannot do them. Any other value,
#: including unset, leaves them served (see the module docstring for why the
#: default is not the fail-closed one every other switch here uses).
DOOR_WRITE_ENV = "ASSISTANT_DOOR_WRITE"

#: Rides on every write tool, so it says only what a call needs; the whole rule
#: (who it authorizes, what 'the assistant' alone may do) is the capability block's,
#: rendered once into AGENTS.md (`workspace/capabilities.py`).
_REQUESTER_DESCRIPTION = (
    f"Who asked you, as your people registry spells them; '{ASSISTANT_NAME}' when nobody "
    "asked. An unknown name is refused."
)

#: The write tools the door serves, in the order a reader meets them. An
#: explicit list rather than every binding `write_tools` holds: what leaves
#: this pod is a decision per tool, and a decision cannot be a
#: `for` loop over a registry that a later commit adds to.
WRITE_TOOL_NAMES: tuple[str, ...] = (
    write_tools.AGENDA_ACT,
    write_tools.CREATE_VIDEO_CALL,
    write_tools.MESSAGE_TEAMMATE,
    write_tools.GITHUB_ACT,
    write_tools.MANAGE_WORKLIST,
    write_tools.REMEMBER_PRINCIPLE,
    write_tools.REMEMBER_NOTE,
    write_tools.PERSONAL_RULE,
    write_tools.RECORD_ANSWER,
)


def read_definitions() -> list[dict[str, Any]]:
    """The read-only investigation tools, exactly as the loops declare them."""
    return tools.investigation_definitions()


def door_writes_enabled() -> bool:
    """Whether the door serves its write half at all right now.

    Read on every call rather than at import, because the container picks up a
    changed secret on restart and a lever nobody can pull without a deploy is
    not a lever.
    """
    return os.environ.get(DOOR_WRITE_ENV, "").strip() != "0"


def write_definitions() -> list[dict[str, Any]]:
    """The write tools, each with the required requester argument added.

    Empty while the write half is switched off, so one read of one env decides
    the catalogue, the dispatch path and what the prompt says the assistant can do.
    """
    if not door_writes_enabled():
        return []
    return [
        _with_recipient_languages(_with_requester(definition))
        for definition in write_tools.definitions(list(WRITE_TOOL_NAMES))
    ]


def served_definitions() -> list[dict[str, Any]]:
    """The whole catalogue the door offers: read tools first, then writes."""
    return read_definitions() + write_definitions()


def is_served_write_tool(name: str) -> bool:
    """Whether `name` is one of the write tools this door serves.

    Asked by the door to pick the dispatch path, so it must answer for the
    served list and not for every binding `write_tools` holds: a write tool
    that is registered in the container but not offered here is refused by name, not
    dispatched. It answers no for all of them while the write half is off, so
    the switch cannot leave a listed-nowhere tool still callable.
    """
    return door_writes_enabled() and name in WRITE_TOOL_NAMES


def _with_requester(definition: dict[str, Any]) -> dict[str, Any]:
    """One write tool's definition with `requested_by` required on its schema.

    Deep-copied first: the original dict is the module-level DEFINITION the
    in-container loops hand to Anthropic, and mutating it would add an argument to
    every loop's tool surface as a side effect of the door being built.
    """
    served = copy.deepcopy(definition)
    schema = served.setdefault("input_schema", {"type": "object"})
    schema.setdefault("properties", {})[REQUESTER_ARGUMENT] = {
        "type": "string",
        "description": _REQUESTER_DESCRIPTION,
    }
    required = list(schema.get("required", ()))
    if REQUESTER_ARGUMENT not in required:
        required.append(REQUESTER_ARGUMENT)
    schema["required"] = required
    return served


#: How a language code from `people.language_for` is spelled to the model.
_LANGUAGE_NAMES = {"en": "English", "nl": "Dutch"}


def _with_recipient_languages(served: dict[str, Any]) -> dict[str, Any]:
    """`message_teammate`'s served definition with each teammate's language
    written into its `person` argument; every other definition unchanged.

    The draft starts in the language of the thread the model is in, and
    when teammates write in another language than the owner reads, a relay to
    the owner comes out in theirs and is refused. The refusal stays as the backstop; this
    puts the answer where the message is written. `served` is already a deep
    copy (`_with_requester`), so the module-level DEFINITION is untouched.
    """
    if served["name"] != write_tools.MESSAGE_TEAMMATE:
        return served
    readers = "; ".join(
        f"{name} reads {_LANGUAGE_NAMES.get(people.language_for(name) or '', 'an undeclared language')}"
        for name in people.names()
    )
    if not readers:
        return served
    person = served["input_schema"]["properties"]["person"]
    person["description"] = (
        f"{person['description']} Write the message in the language this "
        f"person reads, not the one you are being spoken to in: {readers}."
    )
    return served
