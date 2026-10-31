"""The assistant's voice: one register for every message it sends, so its
messages read like a person talking and flow from one to the next.

Every loop that produces human-facing text pastes `render()` into its
prompt through `self_context.render`, the same way they all share
`principles.render()`. One voice means the phone reads as ONE colleague
in one ongoing thread instead of six differently-clipped robots taking
turns.

THERE IS ONE COPY OF THE HOUSE VOICE, and it is `.claude/soul.md`. A paraphrase here would drift from it, rules would go missing, and the
assistant would break them. `render()` reads soul.md itself, so a rule the owner
changes in the repository reaches the assistant on the next deploy. The Dockerfile
copies it in beside `docs/bible.md` and `CONTEXT.md`.

ONE RULE IS REPLACED RATHER THAN CARRIED. Ours says English only, because the
engineering surface is English; the assistant writes to each person in
their own language, because not every reader works in English. That swap is the only edit
made to the house rules here, and Signal's two constraints are appended
after them.

Why it is short: a block that grows by adding prose for every tone correction
ends up contradicting itself, for example claiming "a read-only shell" in one
paragraph and "NO bash, NO ssh, NO terminal on the VM" in another. Both are
half true (the shell runs inside the container, never on the VM), and a model
settles such a contradiction the worst way: by handing the reader the command
instead of running it. So the capability boundary is stated once, precisely,
with the rule about what to say when a check is out of reach.

Prose here is a request, not a rule. SOME of it is also enforced, and
which part is not obvious from reading the block, so here is the sorting: em dashes, markdown,
command syntax and invented transcripts are removed or refused at the
send seam in `signal_text.py`, language and healthy-number readouts are
nudged and may survive the nudge, and the rest is a request and nothing
more. Keep this block to its own rules and its length capped, so the next
correction replaces a rule rather than adding another layer of prose.

The two capability paragraphs are split out below as `_VM_CAPABILITIES`, and
they are SPLIT rather than moved. `self_context.render` pastes `render()` into
every loop unconditionally, triage included, and triage is the road from an
Alertmanager webhook to somebody's phone; a loop that lost those paragraphs
would lose "never invent console output or a debugging transcript", which is
a known failure mode. `render(vm_capabilities=False)` omits them
for a caller that is NOT the container, and the only such caller today is
`apps/assistant/workspace/soul.py`, which renders the gateway's own
boundary in their place. The default is True, so every existing caller gets
the same bytes it got before.

Single public callable: `render()`.

FAILURE POLICY: constants only, nothing to fail.
"""
from __future__ import annotations

from apps.assistant.shared.name import ASSISTANT_NAME

import pathlib
import re

#: The house voice, as the repository writes it. Baked into the image beside
#: `docs/bible.md`; read at import so a missing file stops the container from
#: starting rather than letting it page with no voice at all, which is the
#: failure nobody would see.
_SOUL = pathlib.Path(__file__).resolve().parents[3] / ".claude" / "soul.md"

#: The house rule this pod does not carry: ours is English-only because the
#: engineering surface is, and the assistant answers each person in their
#: own language instead.
_ENGLISH_ONLY = "English only."

#: The one clause inside a kept rule that does not survive the crossing: it
#: tells the reader to write a new term into `CONTEXT.md`, and the assistant has no
#: tool that writes that file. An instruction a model cannot carry out is how
#: it starts claiming it did.
_GLOSSARY_CLAUSE = (
    "When the user introduces a new term, add it to CONTEXT.md (definition "
    "plus _Avoid_ aliases) before you use it. "
)

_LANGUAGE_RULE = (
    "- Write to each person in their language: the one their profile gives, English when "
    "it gives none. USER.md says which."
)

_SIGNAL_RULES = """Two things Signal forces. It renders markdown literally, so no bullets, no
numbering, no key-value pairs, no headers, no emoji. And it is one continuous
thread, so connect what relates to what you said before ("that cost alarm this
morning was the audit only seeing one project"); when it is new, just start
with what happened."""


def _house_rules() -> str:
    """The bullets of `.claude/soul.md`, minus the English-only rule.

    The title line goes; every bullet is kept as written, because the point of
    reading the file is that nobody paraphrases it again. A bullet may wrap
    over several lines, so the split is on the bullet marker at line start.
    """
    bullets = re.split(r"^- ", _SOUL.read_text(), flags=re.MULTILINE)[1:]
    kept = [
        b.replace(_GLOSSARY_CLAUSE, "").rstrip()
        for b in bullets
        if not b.startswith(_ENGLISH_ONLY)
    ]
    if len(kept) != len(bullets) - 1:
        raise ValueError(
            f"{_SOUL} no longer carries exactly one {_ENGLISH_ONLY!r} rule; "
            "the swap this module makes has to be re-decided by a person"
        )
    return "\n".join(f"- {b}" for b in kept)


_VOICE_OPENING = f"""YOUR VOICE, in every message and page:

You are {ASSISTANT_NAME}, the team's assistant: one colleague in one ongoing Signal thread,
not a monitoring system. Sign nothing, but answer to your name.

{_house_rules()}
{_LANGUAGE_RULE}

{_SIGNAL_RULES}"""

# The machine-specific half of the voice: what this container can reach and what it
# cannot. It is a capability statement wearing a voice rule's clothes, which is
# why it is the one part a caller can ask to leave out. The second paragraph's
# closing rules (never hand over a command, never invent a transcript) are
# behaviour and not machine facts, so any caller that omits this block owes the
# reader its own copy of them.
_VM_CAPABILITIES = f"""WHAT YOU CAN CHECK, and are expected to, as real tool calls before saying
anything about live state: Prometheus, Loki when it is wired, the ops
database, GitHub, the calendars, the cluster when one is wired (kubectl get,
logs, describe, events), and a read-only shell inside your own container.

WHAT YOU CANNOT FROM THIS CONTAINER: a shell on the server, docker, ssh, or the
server's journal. What the OOM killer took is in Prometheus when the node
exporter reports it. Say
what you read and what you found. When the cause is only in a VM unit's
journal, say {ASSISTANT_NAME} reads that journal in chat, and name only a unit a tool
result showed you. Never write a next step for the reader that you or the
system can take yourselves. NEVER hand the reader a command to type: that is
making a person do the part you could not, dressed up as help. Never write
command syntax, never emit tool-call markup, and never invent console output
or a debugging transcript."""

# The language rule inside the voice block is reinforcement, not
# enforcement. Prose in a prompt is a request; a reader can get the wrong language three
# separate ways with a paragraph saying exactly that in place. The
# enforcement is `core/claims.py` checking a draft against
# `people.language_for`, and it stays there.
_VOICE = _VOICE_OPENING + "\n\n" + _VM_CAPABILITIES


def render(*, vm_capabilities: bool = True) -> str:
    """The voice block for every human-facing prompt.

    `vm_capabilities=False` drops the two paragraphs about what this pod can
    and cannot reach, for a caller rendering the voice for a DIFFERENT machine.
    Everything else is unchanged, and the default is what every loop in this
    pod gets.
    """
    if vm_capabilities:
        return _VOICE
    return _VOICE_OPENING
