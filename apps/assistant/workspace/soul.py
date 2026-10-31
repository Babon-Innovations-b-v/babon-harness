"""SOUL.md: how the assistant thinks and how the assistant writes, rendered from the container's own
doctrine and voice.

`core.principles.render` and `core.voice.render` are the two blocks every loop
in the container pastes into its system prompt. Upstream OpenClaw assembles its own
prompt and takes this file as one of the pieces, so the same two blocks arrive
the same way and there is no second copy to drift.

Two carve-outs, both deliberate, both additive at the source rather than a
rewrite here.

THE GROUNDING CONTRACT does not travel. Its first four clauses are the price a
TOOL-FREE call pays for being unable to check anything, and its own last clause
says so. The gateway's chat carries tools on every turn, so shipping the
contract would bind a loop the contract itself exempts. The receipts rule that
matters survives anyway: it is the seed principle that forbids stating a
system fact no tool gave this turn, and the seed always renders.

THE VM CAPABILITY PARAGRAPHS do not travel either, and this is the sharp one.
`core.voice` says "you have nothing on the VM, no shell there, no docker, no
ssh", which is true of the container and false of a container running on that VM. It
is NOT moved out of `core.voice`: `core.self_context` renders `voice.render()`
unconditionally for every loop, including triage, which is the road from an
Alertmanager webhook to somebody's phone, so moving the text would delete it
from the loops that page. `voice.render(vm_capabilities=False)` omits exactly
those two paragraphs and nothing else, and this file appends its own paragraph,
written for the machine the gateway actually runs on. The half that is a
behaviour rule rather than a machine fact, never hand the reader a command and
never invent a transcript, is repeated verbatim below, because it is the
failure mode already on record and no capability list produces it.

Public callables: `render_soul()`.

FAILURE POLICY: Tier-1 fail-loud. `principles.render` is itself Tier-2 and
falls back to the seed when the learned-principles read fails, which is its
call to make; anything worse than that raises here and nothing is written.
"""
from __future__ import annotations

from apps.assistant.shared.name import ASSISTANT_NAME

from apps.assistant.core import voice

_HEADING = f"""# SOUL.md

Rendered from the repository every deploy; an edit here does not survive. Change the doctrine by teaching {ASSISTANT_NAME} a principle, or change
the source."""

# The gateway's own capability boundary. It replaces the container's two paragraphs
# and keeps their second half word for word: "never hand the reader a command"
# and "never invent console output" are behaviour rules, not machine facts, and
# fabricating a debugging transcript is the failure this whole boundary was
# written for.
_GATEWAY_CAPABILITIES = """WHAT YOU CAN CHECK, and are expected to, before
saying anything about live state: whatever your tools actually return to you
this turn. Your tools are the ones your host has registered for you and no
others. If you are not sure you have one, try it and report what came back,
never assume you have an access you have not used.

WHAT YOU CANNOT: anything you have no tool for. You do not get to reason your
way to a reading. When the answer is out of reach, say what you can see and
what you cannot: "the webhook dispatcher failed at 19:12 local, and I
can't see that service's state from here, so I don't know why yet." NEVER hand
the reader a command to type. A message ending in "run sudo systemctl status X
on the VM" is you making a person do the part you could not, dressed up as
help. Never write command syntax into a message, never emit tool-call or
angle-bracket markup, and never invent console output or a debugging
transcript; a made-up transcript is worse than saying you do not know."""


def render_soul() -> str:
    """The rendered SOUL.md: the operating principles without the tool-free
    grounding contract, the house voice without the container's machine facts, the
    gateway's own capability boundary, and then the tools it actually has,
    named. The last part is last on purpose: the doctrine above it says "never
    guess your own access, read it there", and with nothing there to read but
    a paragraph saying the tools are whatever the host registered, the
    assistant would claim tools it has not got."""
    return "\n\n".join(
        (
            _HEADING,
            voice.render(vm_capabilities=False),
            _GATEWAY_CAPABILITIES,
        )
    )
