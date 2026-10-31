"""What the assistant in the gateway can actually reach, named tool by tool.

Why this file exists. The seed doctrine tells the assistant "you ARE the
team's assistant and you DO act for them", names `agenda_act` and
`message_teammate` in principle 18, and closes with "never guess your own
access, read it there". If "there" is only a paragraph saying its tools are
whatever its host registered, the assistant will claim the tools the doctrine
names whether it has them or not. A vague boundary loses to a specific
instruction, which is what a vague boundary always does.

So this block is specific and it is DERIVED. Every name comes from
`core.tools.gateway_surface`, the module the MCP door in `gates/mcp.py` builds
its catalogue from, so the two cannot drift: a tool added to the door appears
here on the next deploy, and a tool that never reached the door is listed as
missing whether or not anybody remembered to say so. The block has three
sections and the headings are constants, so a test can hold each section to the
door rather than searching the prose for a name.

Since the write tools were carried over the door the block also
says what the assistant CAN do, and says the thing that half of it turns on: each write
carries the name of the person who asked, and a name the people registry does
not hold is refused with nothing written. The assistant has to be told that, because it
is the one argument no in-container loop ever supplies. The acting section disappears
entirely when the write half is switched off (`ASSISTANT_DOOR_WRITE=0`), and the
nine move into the section that says the assistant cannot: what the container HAS is
`write_tools.all_names()` and what the door SERVES is
`gateway_surface.write_definitions()`, so the two halves of the block are
measured against different things and one can really be shorter than the other.

The door is not the only road the gateway has into the project. The same config
fragment that points it at the door (`gateway_config_patch.json`) also wires
two VM-local MCP servers straight into it, the journal reader and the mail
box. A block that named the door alone and then said anything not named was
impossible would make the assistant deny tools that sit in its tool list,
such as `journal_read`. Those servers are read off the fragment too, every one whose
`toolFilter.include` names its tools, so a server added there is named here on
the same deploy.

It reports OUR half only. Upstream OpenClaw gives the gateway tools of its own
(its own memory, web search, a shell, its workspace files), and this package
cannot see them, so it does not describe them; the paragraph says as much
rather than implying the list is the whole world.

Single public callable: `render_capabilities()`. The section headings are
public with it, for the test that pins block against door.

FAILURE POLICY: Tier-1 fail-loud. A registry that cannot be read is a block
that would understate the assistant's access, and understating it is how it starts
telling people it cannot do things it can.
"""
from __future__ import annotations

from apps.assistant.shared.name import ASSISTANT_NAME

import json
from pathlib import Path

from apps.assistant.core.tools import gateway_surface, write_tools

#: The gateway config fragment this repository owns. Its `mcp.servers` are the
#: other roads into the project besides the door, read here rather than restated.
_CONFIG_PATCH = Path(__file__).with_name("gateway_config_patch.json")

#: The three sections, by their opening words. A test splits the block on these
#: to check that what the door serves is described as reachable and what it does
#: not serve is described as absent, rather than merely appearing somewhere.
READ_HEADING = "YOUR PROJECT TOOLS"
WRITE_HEADING = "WHAT YOU CAN CHANGE"
ABSENT_HEADING = "WHAT YOU STILL CANNOT DO"
VM_HEADING = "ALSO YOURS, served on the ops VM itself"
DRAFT_TOOL = "draft_mail"


def _read_names() -> tuple[str, ...]:
    """Every looking-only tool the door serves, alphabetically."""
    return tuple(sorted(
        definition["name"] for definition in gateway_surface.read_definitions()
    ))


def _write_names() -> tuple[str, ...]:
    """Every tool the door serves that changes something, alphabetically."""
    return tuple(sorted(
        definition["name"] for definition in gateway_surface.write_definitions()
    ))


def _vm_servers() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Each VM-local MCP server the gateway is wired to, with its tool names.

    A server is one whose `toolFilter.include` lists its tools; the door has no
    filter, because the door's own catalogue is the list, and is described by
    the sections above.
    """
    servers = json.loads(_CONFIG_PATCH.read_text(encoding="utf-8"))["mcp"]["servers"]
    return tuple(
        (name, tuple(sorted(server["toolFilter"]["include"])))
        for name, server in sorted(servers.items())
        if server.get("toolFilter", {}).get("include")
    )


def _absent_names() -> tuple[str, ...]:
    """The write tools the container has and the door does not serve, alphabetically.

    Measured against `write_tools.all_names()`, the container's whole registry, and
    not against the door's own decided list. Both ways of taking a tool off the
    door edit that list (a name removed from `WRITE_TOOL_NAMES`, or the whole
    half switched off with `ASSISTANT_DOOR_WRITE=0`), so a comparison with it can
    only ever say "nothing is missing" and the section would be dead prose.
    The registry keeps all nine either way, so a withdrawn tool shows up here.

    Empty today, and it stays in the render because the door is a decision per
    tool: the day one is taken back off it, this is what stops the
    doctrine's promise standing unanswered again.
    """
    served = set(_write_names())
    return tuple(sorted(
        name for name in write_tools.all_names() if name not in served
    ))


def _read_section() -> str:
    """The looking half, named tool by tool."""
    return (
        f"{READ_HEADING}, the whole list, so you never have to guess. These "
        "look and change nothing: " + ", ".join(_read_names()) + "."
    )


def _write_section() -> str:
    """The acting half, plus the argument that makes an action attributable."""
    return (
        f"{WRITE_HEADING}, and these really do it, they are not drafts: "
        + ", ".join(_write_names())
        + f". Every one of them needs `{gateway_surface.REQUESTER_ARGUMENT}`: "
        "the name of the person who asked you, as your people registry spells "
        "it. It is who the action is recorded as and who it is authorized as, "
        "so it is the person who actually asked in this conversation, never a "
        f"guess; when nobody asked, it is '{ASSISTANT_NAME}', which the worklist, notes, a "
        "message and the agenda accept and nothing else does. A name the registry does not hold is "
        "refused and nothing is written. Every one of these is written into "
        "your action log under that person's name BEFORE it runs, so say "
        "plainly when you have done one, and never use somebody's name to get "
        "an action through."
        + _answer_sentence()
    )


def _answer_sentence() -> str:
    """The one line saying when to record an answer, if the door serves it.

    A reply reaches only this session, so recording it is the model's call to
    make here or nowhere.
    """
    if write_tools.RECORD_ANSWER not in _write_names():
        return ""
    return (
        f" When a message answers something on your worklist, call "
        f"{write_tools.RECORD_ANSWER} before you reply, or it will be asked "
        "again. A relayed \"[Sent by me to\" line names the item it concerns "
        "when it knows it, and otherwise lists the open item ids it may "
        f"concern; when neither is there, call {write_tools.MANAGE_WORKLIST} "
        "list before deciding a message answers nothing."
    )


def _vm_section(servers: tuple[tuple[str, tuple[str, ...]], ...]) -> str:
    """The tools the gateway reaches without the door, server by server."""
    return (
        f"{VM_HEADING}, outside the list above and just as real: "
        + "; ".join(f"{name}: {', '.join(tools)}" for name, tools in servers)
        + ". Before you say something on a VM is out of your reach, look "
        "here as well as above."
        + _draft_sentence(servers)
    )


def _draft_sentence(servers: tuple[tuple[str, tuple[str, ...]], ...]) -> str:
    """The line that makes drafting a mail the assistant's job, only when draft_mail is wired in.

    The tool's own description already says it never sends. What the gateway
    lacked was the step: the seed principle "You send no email" read as "mail
    is the human's job", so the assistant would answer "I don't do email
    out" and leave the person the whole reply to a contact. The container has no
    draft_mail, so this lives here and not in the shared seed.
    """
    if not any(DRAFT_TOOL in tools for _name, tools in servers):
        return ""
    return (
        " When a mail reply or a chase is the next step for someone, save it "
        f"with {DRAFT_TOOL} in their own Drafts folder and say it is there. "
        "\"You send no email\" means you never press send; never tell someone "
        "you don't do email."
    )


def _absent_section(absent: tuple[str, ...]) -> str:
    """The tools the doctrine names that the door does not serve."""
    return (
        f"{ABSENT_HEADING}: your principles name these and you do not have "
        "them here: "
        + ", ".join(absent)
        + f". They belong to the {ASSISTANT_NAME} that runs in the pod. When somebody asks "
        "you for one of those things, say plainly that you cannot do it; do "
        "not describe it as done, and do not offer to do it later as though "
        "you could."
    )


def render_capabilities() -> str:
    """The capability block the seed doctrine tells the assistant to read."""
    sections = [_read_section()]
    if _write_names():
        sections.append(_write_section())
    servers = _vm_servers()
    if servers:
        sections.append(_vm_section(servers))
    sections.append(
        "Your host gives you tools of its own as well (its memory, web "
        "search, a shell and your workspace files). Those are real and this "
        "list does not cover them. What this list is complete about is the project: if a thing "
        "you want to do to the project's systems is not a tool named above, you "
        "cannot do it."
    )
    absent = _absent_names()
    if absent:
        sections.append(_absent_section(absent))
    return "\n\n".join(sections)
