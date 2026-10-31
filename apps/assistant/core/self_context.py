"""One self-context assembler, who the assistant is and what it knows right now,
rendered the same for every loop.

Hand-written per-loop prompt tuples drift apart: the identity spine
(principles + voice + journal) gets copy-pasted, and `awareness.render()`,
the local clock and the exact today/tomorrow date table that keeps the model
from booking events on the wrong day, reaches only some loops. This owns the
assembly once, so the assistant is provably the same colleague in every loop.

`render(loop, task, ...) -> str` builds the system prompt. Every loop gets the
SPINE: principles (how it judges), voice (how it writes), journal (what it
knows: compacts + notes), awareness (the current picture, INCLUDING the date),
and recent_sent (what it recently told people). A small per-loop `LoopSpec`
adds the rest:
- `worklist`: the jobs it carries, for loops that act on it (chat, patrol,
  morning).
- `include_all_clear`: whether patrol all-clear notes and green-telemetry
  findings ride into the prompt. The morning brief says no: a healthy readout
  travelling in as if it were news would put green telemetry into the brief.
- `audience`: people + capabilities blocks, only when a specific person is
  being addressed (chat), so a teammate's tone rule and the assistant's honest account
  of its own calendar access follow the conversation.
- `recent_actions`: the assistant's own action log (`assistant_actions`, board edits,
  calendar writes, teammate messages) for the loops that act toward third
  parties (chat, patrol). `recent_sent` covers what it told the CURRENT person;
  this covers what it DID to others, so a confirming question ("did you send
  the nudge?") is answered from memory instead of re-executed.
`extra` blocks (a loop's genuinely unique input, e.g. morning's support inbox)
are appended before the task, which always comes last.

`compact` does NOT use this, it folds raw memory and speaks to no one, so it
keeps its own minimal principles-only prompt.

FAILURE POLICY: Tier-2. Each block renderer already degrades on its own (an
awareness read that fails returns an empty block); assembly just drops empty
blocks. No new failure surface.

Single public callable: `render()`. `LoopSpec` and the `_SPECS` table are the
per-loop declaration.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from apps.assistant.core import awareness as _awareness
from apps.assistant.core import capabilities as _capabilities
from apps.assistant.core import journal as _journal
from apps.assistant.core import outbound as _outbound
from apps.assistant.core import people as _people
from apps.assistant.core import principles as _principles
from apps.assistant.core import state as _state
from apps.assistant.core import voice as _voice


@dataclass(frozen=True)
class LoopSpec:
    """What a loop gets on top of the shared spine. `audience` turns
    on the people + capabilities blocks when a sender is known. `recent_actions`
    adds the assistant's own action log (what it DID, not just said) for the loops that
    act toward third parties and get asked to confirm it. `include_all_clear`
    keeps the journal's all-clear notes and the worklist's green findings in
    the prompt; the morning brief switches it off."""

    worklist: bool = False
    audience: bool = False
    recent_actions: bool = False
    include_all_clear: bool = True


_MAX_ACTION_ROWS = 10


def _recent_actions_block() -> str:
    """the assistant's own recent action log (`assistant_actions`) as a prompt block: the
    board edits, calendar writes and teammate messages it already made.

    Without this, a loop's context shows what the assistant SAID to the current sender
    (`recent_sent`) but not what it DID to others, so a confirming question
    ("did you send the nudge?") reads as a fresh command and the action is
    repeated, double-texting a teammate. Timestamped so the
    answer is "yes, sent it at 17:02", not another send.
    """
    try:
        actions = _state.recent_actions(_MAX_ACTION_ROWS)
    except Exception:  # noqa: BLE001, Tier-2: context, not correctness
        return ""
    if not actions:
        return ""
    lines = [
        "WHAT YOU RECENTLY DID, your own action log (board, calendar, "
        "messages you already sent). You DID these; if someone asks whether you "
        "did one, READ IT HERE and report it, do NOT do it again:"
    ]
    for action in actions:
        stamp = str(action.get("created_at", ""))[11:16]
        summary = str(action.get("summary", ""))[:100]
        lines.append(
            f"[{stamp}Z] {action['kind']} -> {action['target']}: {summary} ({action['actor']})"
        )
    return "\n".join(lines)


# The per-loop declaration. The SPINE (principles, voice, journal, awareness,
# recent_sent) is unconditional and NOT listed here, every loop gets it, which
# is the point: triage/patrol/digest/security now all know the date and
# what the assistant recently did. Only the extras differ.
_SPECS: dict[str, LoopSpec] = {
    "triage": LoopSpec(),
    "patrol": LoopSpec(worklist=True, audience=True, recent_actions=True),
    "digest": LoopSpec(),
    "security": LoopSpec(),
    "notify": LoopSpec(audience=True),
    # Filing a corrected set of minutes onto the board. No worklist
    # and no audience: the whole input is one meeting and one listing of the
    # open board, both handed over in the user turn, and every choice is an
    # enum over them. What this loop needs from the spine is the date and the
    # principles; anything else would be a second opinion about a document it
    # has already been given in full.
    "notulen": LoopSpec(),
}


def render(
    loop: str,
    task: str,
    *,
    sender: str | None = None,
    sender_uuid: str | None = None,
    extra: Sequence[str] = (),
    worklist_exclude_keys: Sequence[str] = (),
) -> str:
    """Assemble the system prompt for `loop`: the shared spine, the loop's
    declared extras, any caller-supplied `extra` blocks, then `task` last.
    Empty blocks are dropped. Unknown `loop` raises (a new loop must declare a
    spec).

    `worklist_exclude_keys` are `reported_items` keys the caller has already
    rendered as carried one-liners; the worklist block leaves those items out
    so the same item is not rendered twice, once as a one-liner and once in
    full. It is threaded through here because this is the only place in `core`
    that calls `worklist.render`: a second call in the caller would produce
    exactly the double rendering the exclusion exists to prevent."""
    spec = _SPECS[loop]

    blocks: list[str] = [
        _principles.render(),
        _voice.render(),
        _journal.render(include_all_clear=spec.include_all_clear),
        _awareness.render(),
        _outbound.recent_sent(),
    ]
    if spec.worklist:
        blocks.append(
            _state.worklist.render(
                exclude_keys=worklist_exclude_keys,
                include_all_clear=spec.include_all_clear,
            )
        )
    if spec.recent_actions:
        blocks.append(_recent_actions_block())
    blocks.extend(extra)
    if spec.audience:
        # A loop with no inbound sender still has a READER: the morning brief,
        # the patrol note and the notify batch all land in the same
        # thread as chat, addressed to the page recipient. Defaulting to that
        # recipient is why a rule taught in chat ("English only with me") now
        # governs those loops too instead of binding in chat only.
        audience_sender = sender if sender is not None else _outbound.recipient()
        if audience_sender is not None:
            blocks.append(_people.render(audience_sender, sender_uuid))
            blocks.append(_capabilities.render(audience_sender, sender_uuid))
    blocks.append(task)

    return "\n\n".join(block for block in blocks if block)
