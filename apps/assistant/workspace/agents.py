"""AGENTS.md: what the assistant must do, kept out of the file that says how it writes.

Upstream injects five workspace files and takes each as a separate piece of the
prompt: AGENTS.md, SOUL.md, IDENTITY.md, USER.md and, on a first run only,
BOOTSTRAP.md. Using one of those five for two jobs at once, SOUL.md carrying
the operating principles AND the house voice, buries the voice under the
principles.

That is why a length cap in a report's own prompt works where the voice
alone does not. The voice already said "Length tracks the answer, never the question.
Write the shortest version that is still fully clear, then stop"; it sat at the
bottom of a wall of doctrine telling the assistant to check, verify, caveat, surface and
always say what it would do, and the wall wins. So the assistant gets the
same voice file the owner works with, and the principles live in a file of
their own.

So the doctrine moved here. Nothing is hidden by the move, because upstream
injects this file too; what changes is that the voice is no longer read as a
footnote to a rulebook.

WHAT THIS FILE DOES NOT DO, and it is the reason it is not a straight copy of
upstream's own AGENTS.md. Upstream writes one on first run telling the agent to
maintain `USER.md` and `MEMORY.md` itself. Ours does not: `USER.md` is rendered
from the people registry by the deploy of every commit, so an edit the assistant makes
there is gone within the hour and it should not be told to make one. The
memory it really keeps is its journal, its worklist and its principles table,
all on the container's volume behind tools, and those are what this file points at.

Public callables: `render_agents()`.

FAILURE POLICY: Tier-1 fail-loud, the same as its siblings. `principles.render`
is itself Tier-2 and falls back to the seed when the learned table cannot be
read, which is its call; anything worse raises here and the caller writes
nothing, so the gateway keeps the last complete set.
"""
from __future__ import annotations

from apps.assistant.core import principles
from apps.assistant.workspace import capabilities

_HEADING = """# AGENTS.md

Rendered from the repository every deploy; an edit here does not survive.

SOUL.md says how you write. This file says what you do."""

# Where the assistant's memory actually lives. Upstream's own AGENTS.md points at
# `memory/YYYY-MM-DD.md`, `USER.md` and `MEMORY.md`; two of those three are
# wrong here, and a file telling the assistant to maintain something the deploy
# overwrites is worse than silence, because it produces work that vanishes.
_MEMORY = """WHAT YOU REMEMBER, and where.

Your journal is what you know: facts you have learned, with the date you
learned them. Your worklist is what you are carrying: things you are watching,
things you are looking into, and questions you have asked and not had answered.
Your principles are how you work, and the owner is the only one who adds to them.
All three live behind your own tools; use those, and nothing else.

You do not maintain your own workspace files. USER.md is rendered from the
company's people registry every deploy, so an edit you make there is gone
within the hour: when a teammate tells you how they want to be talked to,
record it as a personal rule for that person and it reaches USER.md the proper
way. The same is true of this file and of SOUL.md.

What you sent from elsewhere arrives here on its own. The weekday brief, the
advisor, your pages and your reminders are sent from other sessions, and within
a few minutes each one reaches you as a `System:` line at the top of the next
message, starting "[Sent by me to" and naming who it went to, when and from
where. A short reply is most likely answering the newest of those lines, not
an older thread, and how people answer them is how you learn what lands. `my_actions` lists every message you sent anyone: read it before
you say you did or did not send something."""


def render_agents() -> str:
    """The rendered AGENTS.md: the heading, the operating principles without
    the tool-free grounding contract, where memory lives, and the tools the assistant
    actually has.

    The tool inventory is here rather than in SOUL.md because it is what the assistant
    can DO, which is this file's subject. It has to be somewhere the model
    reads: doctrine tells it "never guess your own access, read it there", and
    with nothing there to read it would claim tools it has not got.

    The grounding contract is left off for the reason `soul.py` gives: its
    clauses are the price a call with no tools pays for being unable to check
    anything, and its own last clause says a loop that HAS tools keeps the
    ordinary receipts discipline instead. Every turn through the gateway
    carries tools.
    """
    return "\n\n".join(
        (
            _HEADING,
            principles.render(grounding=False),
            _MEMORY,
            capabilities.render_capabilities(),
        )
    )
