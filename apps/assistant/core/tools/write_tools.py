"""Registry of the assistant's chat-driven WRITE tools + the one place the DRIVER
binds to each.

The read-only investigation tools live in the shared dict registry
(`tools.execute`). The write tools are different: each needs the driver
bound to it (who taught the principle, owns the worklist item, is the board
actor, which loop the note came from). Before, every loop offering a write
tool hand-rolled both its DEFINITION list and an `if name == X.NAME: return
X.execute(.., <its own kwarg>)` branch, so one concept ("who is driving")
wore five names (actor / owner / taught_by / person / source) across two
dispatch chains.

Here each write tool is registered once with HOW its driver binds, via one
`Actor`. A loop declares the write tools it wants by NAME and dispatches
them uniformly; adding a write tool is one entry in `_BINDINGS`, not seven
edits across two files. Read-only loops declare NO write tools, so the
the read-only guarantee is a property you can see and test, not one
smeared across loop files.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from apps.assistant.core.tools.agenda import agenda_act as _agenda_act
from apps.assistant.core.tools.agenda import create_video_call as _video_call
from apps.assistant.core.tools.gh import github_act as _gh_act
from apps.assistant.core.tools.meta import manage_worklist as _worklist
from apps.assistant.core.tools.meta import personal_rule as _personal_rule
from apps.assistant.core.tools.meta import record_answer as _record_answer
from apps.assistant.core.tools.meta import remember_note as _note
from apps.assistant.core.tools.meta import remember_principle as _remember
from apps.assistant.core.tools.team import message_teammate as _message_teammate


@dataclass(frozen=True)
class Actor:
    """Who is driving a write, resolved once: their people-registry name,
    their Signal UUID when a verified sender carried one, and the loop it came
    from (chat / patrol).

    `evidence` answers what this driver has read lately, as the tool answers'
    texts, so a memory write can be checked against it before it is stored
   . None means the driver keeps no such record, and nothing is checked.
    """

    name: str
    uuid: str | None = None
    loop: str = "chat"
    evidence: Callable[[], Sequence[str]] | None = None


# NAME -> (DEFINITION, bind). `bind(tool_input, actor) -> result string` is
# the ONE place each write tool's driver-binding is spelled out.
_BINDINGS: dict[str, tuple[dict[str, Any], Callable[[dict, Actor], str]]] = {
    _remember.NAME: (_remember.DEFINITION, lambda ti, a: _remember.execute(ti, taught_by=a.name)),
    _personal_rule.NAME: (_personal_rule.DEFINITION, lambda ti, a: _personal_rule.execute(ti, person=a.name)),
    _note.NAME: (_note.DEFINITION, lambda ti, a: _note.execute(ti, source=a.loop, evidence=a.evidence)),
    _worklist.NAME: (_worklist.DEFINITION, lambda ti, a: _worklist.execute(ti, owner=a.name, evidence=a.evidence)),
    _gh_act.NAME: (_gh_act.DEFINITION, lambda ti, a: _gh_act.execute(ti, actor=a.name)),
    _agenda_act.NAME: (_agenda_act.DEFINITION, lambda ti, a: _agenda_act.execute(ti, actor=a.name)),
    _video_call.NAME: (_video_call.DEFINITION, lambda ti, a: _video_call.execute(ti, actor=a.name)),
    _message_teammate.NAME: (_message_teammate.DEFINITION, lambda ti, a: _message_teammate.execute(ti, actor=a.name)),
    _record_answer.NAME: (_record_answer.DEFINITION, lambda ti, a: _record_answer.execute(ti, actor=a.name)),
}

# NAME -> the prefixes a tool's result carries ONLY when the write actually
# landed. A claim of having done something is "backed" only if the tool
# returned one of these: every write tool reports success with a
# distinct, stable opening, and every refusal/error/needs-arg does not. This
# is the receipts check the loops reconcile against, in ONE place.
_SUCCESS_PREFIXES: dict[str, tuple[str, ...]] = {
    # "moved " has to be here: without it every landed move reads as an
    # unbacked claim, and "I moved it" draws a nudge for a write that happened.
    _agenda_act.NAME: ("added ", "moved ", "removed ", "updated ", "cancelled "),
    _video_call.NAME: ("video call ready:",),
    _message_teammate.NAME: ("messaged ",),
    _gh_act.NAME: ("done:",),
    _remember.NAME: ("recorded principle:",),
    _personal_rule.NAME: ("recorded your personal rule:",),
    _note.NAME: ("noted:",),
    _worklist.NAME: ("tracking as worklist item", "noted progress on item", "closed item"),
    _record_answer.NAME: ("recorded answer on item",),
}


def was_success(name: str, result: str) -> bool:
    """Whether a write tool's `result` string means the write actually landed
    (not a refusal, error, or needs-more-input). Used by the loops so the assistant
    can never report an action 'done' without a real successful tool-result."""
    prefixes = _SUCCESS_PREFIXES.get(name)
    return bool(prefixes) and result.lstrip().startswith(prefixes)


# Names, re-exported so a loop declares its write tools without importing
# every tool module itself.
REMEMBER_PRINCIPLE = _remember.NAME
PERSONAL_RULE = _personal_rule.NAME
REMEMBER_NOTE = _note.NAME
MANAGE_WORKLIST = _worklist.NAME
GITHUB_ACT = _gh_act.NAME
AGENDA_ACT = _agenda_act.NAME
CREATE_VIDEO_CALL = _video_call.NAME
MESSAGE_TEAMMATE = _message_teammate.NAME
RECORD_ANSWER = _record_answer.NAME


# The write tools whose answer only repeats what the assistant wrote ("noted: <the
# note>"). Their answers are not evidence: kept as readings, a number the assistant
# wrote into its own note backed its next message. `github_act` is not
# one, because its answer carries what it could not have known before, the
# number of the issue it just opened.
_ECHO_TOOLS = frozenset({
    _remember.NAME, _personal_rule.NAME, _note.NAME, _worklist.NAME,
    _record_answer.NAME,
})


def echoes_its_input(name: str, tool_input: Mapping[str, Any] | None = None) -> bool:
    """Whether `name`'s answer, called with `tool_input`, only repeats what it
    was given to write.

    `manage_worklist` "list" is the exception: it returns the rendered
    worklist, a real reading whose titles carry issue numbers a brief goes on
    to cite.
    """
    if name == _worklist.NAME and str((tool_input or {}).get("action", "")).strip() == "list":
        return False
    return name in _ECHO_TOOLS


def is_write_tool(name: str) -> bool:
    """Whether `name` is a write tool at all, whoever declared it.

    A loop gates its own surface on this: leaving a write tool out of the
    definitions keeps the model from asking for it, but `dispatch` below still
    binds anything in the registry, so the loop that must not reach a tool has
    to be able to say no to it by name."""
    return name in _BINDINGS


def all_names() -> tuple[str, ...]:
    """Every write tool this pod has, in registration order.

    What a SERVED subset is measured against. The MCP door offers a decided
    list rather than the registry, and the capability block has to
    tell the assistant about the tools that are NOT on that list; asking the door's own
    list for both halves compares a set with itself and always answers
    "nothing is missing"."""
    return tuple(_BINDINGS)


def definitions(names: list[str]) -> list[dict[str, Any]]:
    """The DEFINITIONs for the named write tools, in the given order."""
    return [_BINDINGS[name][0] for name in names]


def dispatch(name: str, tool_input: dict[str, Any], actor: Actor) -> str | None:
    """Run a write tool with the actor bound, or None if `name` is not a
    write tool (the caller then falls through to the read-only registry)."""
    entry = _BINDINGS.get(name)
    return entry[1](tool_input, actor) if entry else None
