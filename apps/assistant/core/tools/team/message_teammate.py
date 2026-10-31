"""`message_teammate` tool, the assistant messages a teammate over Signal.

The team plans through the assistant: a teammate asks the assistant to arrange something
("plan the Monday briefing, and ask a teammate to send it"), the assistant puts it in
the team calendar with `agenda_act`, and tells the people involved here, over
the Signal channel they already use. No email, no invitations.

Same safety shape as `agenda_act`/`github_act`:

  1. KILL SWITCH. Refuses unless ``ASSISTANT_TEAM_MESSAGE=1`` in the container env.
  2. BOUNDED AUDIENCE. Only sends to a teammate in the people registry
     (`SIGNAL_PEOPLE`) who carries a send number, never a raw number the
     LLM made up, never someone off the team.
  3. ATTRIBUTED + AUDITED. The message carries who asked (the requester),
     and every send lands in ``state.assistant_actions`` BEFORE it is reported
     done (kind ``team_message``).

Anyone on the allowlist can drive it (the whole point is that the team,
not only the owner, plans through the assistant); the requester rides in as `actor`.

Five deterministic checks run before the send, all in the same refusal
shape (a plain "not sent: ..." string the model can act on, never a raised
exception and never a dropped message):

  * quiet hours, for the assistant's OWN initiative only;
  * weekday-versus-date arithmetic;
  * the recipient's LANGUAGE: a message in the wrong language is easy to send
    with the recipient's language sitting right there in the registry.
    The prompt already asked for the right language; asking is not
    enforcing, so the seam checks it;
  * the recipient being AWAY: a handover to someone on holiday is
    refused with their return date, so it goes on a worklist instead of
    onto the phone of someone on holiday;
  * the message being one this person ALREADY GOT, such as a relayed
    question put to someone again minutes after they answered it. Every other check reads one
    draft on its own, and a duplicate is only wrong in company;
  * the message being TOO LONG. See below;
  * the message being the assistant's WORKING rather than a message, or citing
    what nothing returned: a pasted tool answer, tool-call markup,
    a command line or "let me check ..." narration is refused, and so is an
    issue number no MCP door answer of the last half hour held, read from
    the door's own record (`outbound.door_readings`). That window is shared
    by every gateway session, because the gateway sends no session key;

  * the message saying nothing is broken while an alert that paged is still
    firing, such as a brief saying "nothing broke overnight" seconds after a
    page;

  * the message telling this person a worklist item of THEIRS that they
    have already been told and that has not moved since. `state/reported_items.py` was built for exactly this, and
    without a caller nothing counts a repeat, so one item could reach a person
    on consecutive mornings with the same sentence. The caller is here, because a send is the
    last place that can still tell a repeat from a first telling;

  * the message asking this person about an item they already ANSWERED: a reply lands in the gateway's chat session, which
    records it with `record_answer`, and from then on the item is not put to
    that reader again however the issue moves. The refusal quotes the answer.

THE LENGTH CHECK IS HERE BECAUSE INSTRUCTIONS ALONE DO NOT HOLD. Prose about
being brief (a cap on the number of items, a shorter doctrine, a principle
saying "three sentences or fewer") can be obeyed while the message stays
long, because a sentence has no length. A rule a model can satisfy while
doing the thing the rule forbids is not a rule.

So the number is a word count and lives in code, where it cannot be argued
with, satisfied sideways or quietly dropped by a later session. Scheduling
messages, this tool's actual job, are short; the cap cuts the padding and
leaves the function.

Tool-module grammar: NAME, DEFINITION, execute.

FAILURE POLICY: refusals + a failed send return as text; the audit write
is Tier-1 (propagates to the registry's defended catch, never a silent
skip).
"""
from __future__ import annotations

from apps.assistant.shared.project import GITHUB_REPO

from apps.assistant.shared.zone import LOCAL_ZONE

import datetime as _datetime
import json
import logging
import re
import subprocess
from collections.abc import Sequence
from typing import Any
from zoneinfo import ZoneInfo

from apps.assistant.core import outbound as _outbound
from apps.assistant.core import people
from apps.assistant.core import quiet_hours as _quiet_hours
from apps.assistant.core import signal_text as _signal_text
from apps.assistant.core import state as _state
from apps.assistant.core.tools import write_guard
from apps.assistant.core.tools.agenda import person_away as _person_away
from apps.assistant.shared import signal as _signal

log = logging.getLogger("openclaw.message_teammate")

NAME = "message_teammate"

_ENABLE_ENV = "ASSISTANT_TEAM_MESSAGE"

_LANGUAGE_NAMES = {"nl": "Dutch", "en": "English"}

# How far back "you already sent them this" reaches. An afternoon: long enough
# to cover a conversation that is still going, short enough that a standing
# question put again tomorrow is treated as the new question it is.
_REPEAT_WINDOW_SECONDS = 6 * 3600
_REPEAT_MAX_TURNS = 20

# The most words one Signal message may carry. A ceiling, not a
# target: the ask for a scheduled report asks for one line, and this is what
# stops a bad day becoming a page of prose. 40 refuses padded messages and passes
# the short scheduling messages this tool exists for. Raising it needs a
# measurement, not a feeling: the number is the whole mechanism, because a
# sentence asking nicely is not.
MAX_MESSAGE_WORDS = 40

# An issue number as a person writes one. Both spellings appear: the assistant's own
# worklist titles open "Issue 12: ...", and a message to a person says
# "an issue". Two digits at least, so a "#3" in prose is not read as an issue.
_ISSUE_RE = re.compile(r"(?:#|\bissue\s+)(\d{2,6})\b", re.IGNORECASE)

# Any free-standing number in a message, which is how a person also writes an
# issue: "catering 47 needs your ask to Jordan" matches nothing above, so without
# this the ledger never sees that telling. A bare number is only ever compared against the issue numbers in
# the reader's OWN open worklist titles, never read as an issue on its own. A
# digit run that is part of an amount, a date or a clock time ("9.000",
# "09:30") is not free-standing, so it cannot collide with a title.
_BARE_NUMBER_RE = re.compile(r"(?<![\d.,:])(\d{2,6})(?![\d]|[.,:]\d)")

# The owner a worklist row carries when the assistant opened it itself (the patrol, or
# a door write booked `requested_by: "the assistant"`), as `worklist.add_item` spells it.
_ASSISTANT_OWNER = "assistant"

# The repository a worklist title's issue numbers belong to, and how long one
# read of an issue may hold up a send.
_REPO = GITHUB_REPO
_ISSUE_READ_TIMEOUT_S = 10
_TICKED_BOX_RE = re.compile(r"^\s*[-*] \[[xX]\]", re.MULTILINE)
_OPEN_BOX_RE = re.compile(r"^\s*[-*] \[ \]", re.MULTILINE)

# How far back a door reading still backs a message. Half an hour: a
# brief or an advisor run reads and sends inside a few minutes, and a
# conversation that read an issue earlier in the hour may still cite it. The
# window is UNATTRIBUTED (`outbound.UNATTRIBUTED`): the gateway sends no session
# key, so a reading made by another session counts here too.
_DOOR_READING_WINDOW_SECONDS = _outbound.DOOR_EVIDENCE_WINDOW_SECONDS

# Recipients already refused once this turn for writing in the wrong language.
# One refusal buys one rewrite; a second would let a stubborn draft spend the
# whole iteration cap arguing with a regex, and a message that never goes out
# is a worse failure than a message in the wrong language.
_language_refused: set[str] = set()

# Does the message hand work over? Narrow on purpose: an ask aimed at the
# reader, not any sentence that mentions a task. A miss just lets the message
# through (the away block is still in the prompt), same posture as the claims
# guards; a false positive costs one rewrite.
_HANDOVER_RE = re.compile(
    r"\b(can you|could you|would you|please|i need you to|over to you|"
    r"take (this |it )?over|have a look at|chase|action this|"
    r"kun je|kan je|zou je|wil je|graag|pak (jij|je)|neem .{0,15}? over|"
    r"kijk (even )?naar|regel jij|zorg jij|jouw beurt)\b",
    re.IGNORECASE,
)


DEFINITION: dict[str, Any] = {
    "name": NAME,
    "description": (
        "Send a Signal message to a teammate in your people registry, by name, "
        "and say in it who asked. An unknown name is refused."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "person": {
                "type": "string",
                "description": "Their name as your people registry spells it.",
            },
            "message": {
                "type": "string",
                "description": (
                    f"The whole message, in their language, at most "
                    f"{MAX_MESSAGE_WORDS} words: the one thing they have to act "
                    f"on. Longer is refused."
                ),
            },
            "worklist_items": {
                "type": "array",
                "items": {"type": "integer"},
                "description": (
                    "The id of every worklist item this message is about, so "
                    "the telling is counted even when it names no issue number."
                ),
            },
        },
        "required": ["person", "message"],
    },
}


def execute(tool_input: dict[str, Any], actor: str = "assistant") -> str:
    disabled = write_guard.require_enabled(_ENABLE_ENV, "message teammates")
    if disabled:
        return disabled
    person = str(tool_input.get("person", "")).strip()
    message = str(tool_input.get("message", "")).strip()
    if not person or not message:
        return "message_teammate needs both 'person' and 'message'."

    number = people.number_for(person)
    if not number:
        return (
            f"I have no send number for {person!r} in my people registry, so I "
            "cannot message them. Ask the owner to add them (SIGNAL_PEOPLE), or tell "
            "me who you mean."
        )

    too_long = _too_long_refusal(message)
    if too_long:
        return too_long

    # Quiet hours: the assistant does not START conversations at night. Only
    # its OWN initiative is held (patrol runs as actor "assistant"); a message a
    # teammate asked for right now is their call and goes out.
    if actor == "assistant" and _quiet_hours.quiet_now():
        return (
            f"not sent: it is quiet hours (local time) and nobody asked for "
            f"this right now. Put it on your worklist and message {person} "
            "in the morning."
        )

    # Weekdays are arithmetic, never memory: a message pairing a
    # weekday with a date it never falls on does not go out. Imported lazily:
    # claims reaches write_tools, which imports this module (cycle otherwise).
    from apps.assistant.core import claims as _claims
    today = _datetime.datetime.now(LOCAL_ZONE).date()
    mismatch = _claims.weekday_mismatch(message, today)
    if mismatch:
        return (
            f"not sent: {mismatch}. Fix the weekday or the date (agenda_view "
            "shows the calendar), then send again."
        )

    tool_text = _tool_text_refusal(message, _claims)
    if tool_text:
        return tool_text

    unread = _unread_evidence_refusal(message, _claims)
    if unread:
        return unread

    all_clear = _all_clear_refusal(message, _claims)
    if all_clear:
        return all_clear

    # Who asked has to be IN the message, not only in the audit row. The rule
    # is written in three places (this module's contract line, the tool
    # description, and the manual) and this is where it is checked: a relayed
    # message must not open "I'm sending this on my own initiative". Skipped when the requester IS the recipient,
    # where naming them back at themselves would read as odd rather than clear.
    if person.strip().lower() != actor.strip().lower():
        unattributed = _claims.unattributed_relay(message, actor)
        if unattributed:
            return f"not sent: {unattributed}"

    repeated = _repeat_refusal(person, number, message, _claims)
    if repeated:
        return repeated

    wrong_language = _wrong_language_refusal(person, message, _claims)
    if wrong_language:
        return wrong_language

    handover = _away_refusal(person, message)
    if handover:
        return handover

    # Last of the checks, because it is the only one that reads two tables and
    # the cheap refusals should have run first. Split BEFORE the send and mark
    # AFTER it: `split_candidates` writes nothing, so a send that never lands
    # leaves tomorrow free to say the same thing.
    their_items = _their_items_in(person, message, _listed_ids(tool_input))
    answered = _answered_refusal(their_items, person)
    if answered:
        return answered
    fresh, carried = _state.reported_items.split_candidates(
        _candidates_for(their_items, person)
    )
    repeated_item = _already_told_refusal(carried, their_items, person)
    if repeated_item:
        return repeated_item

    # The message is yours, in your own words: you write the whole thing,
    # including who asked. No preset footer or signature is added here, only
    # the markdown Signal would show literally comes off (`strip_markdown`, the
    # same defanging every other send path gets).
    # Full message in the audit `detail`, so exactly what the assistant sent to whom
    # is recoverable later (the 80-char summary is just for the log line).
    message = _signal_text.strip_markdown(message)
    write_guard.audit("team_message", f"signal {person}", message[:80], actor=actor, detail=message)
    if not _signal.send("", message, recipient=number):
        return f"send to {person} failed (signal-cli); it is logged as a dead-letter."
    # Outbound is memory: record what the assistant said to them in THEIR chat thread
    # (keyed by their send number, the identity they reply from). The gateway's
    # chat session does not read this table; `my_actions` does, and that is how
    # a reply finds the question it answers when this send came from a cron
    # run. Best-effort so a stored-memory hiccup never turns a
    # delivered message into a failure.
    # The loop says whether somebody asked for it: a send booked to the assistant came
    # from a scheduled run or its own initiative. The chat relay copies both
    # into the recipient's own gateway session, which saw neither.
    # The items the message is about go with it, so the relay can tell that
    # session which one a reply answers.
    try:
        _state.append_chat_turn(
            number, "assistant", message,
            loop="teammate-self" if actor.strip().lower() == "assistant" else "teammate-asked",
            worklist_items=tuple(int(item["id"]) for item in their_items),
        )
    except Exception as exc:  # noqa: BLE001, Tier-2: the send already landed
        log.warning("could not record teammate message in %s thread: %s", person, exc)
    # The ledger write, and only now: marking on compose would let a send that
    # failed silence tomorrow's telling of the same item (the ledger's own rule).
    if fresh:
        try:
            _state.reported_items.mark_reported(fresh)
        except Exception as exc:  # noqa: BLE001, Tier-2: the send already landed
            log.warning("could not record what %s was told: %s", person, exc)
    return f"messaged {person}."


def reset_language_gate() -> None:
    """Start a fresh turn: forget who was already refused for language.

    Called by each loop that can drive this tool, so "at most one refusal"
    means one per turn rather than one per pod lifetime.
    """
    _language_refused.clear()


def _tool_text_refusal(message: str, claims) -> str | None:
    """The refusal when the draft is the assistant's working rather than a message, or
    None.

    Two shapes: a tool's answer pasted in ("change_feed: ...") and the
    assistant narrating its next step ("Let me check the current
    state of this service"). Refused whole, never stripped, because
    what is left of a pasted dump is not a message either.
    """
    if (
        claims.pasted_tool_output(message)
        or _signal_text.looks_fabricated(message)
        or _signal_text.names_a_command(message)
    ):
        return (
            "not sent: it carries tool output, tool-call markup or a command "
            "line, which is your working and not a message. Say in plain words "
            "what it means for them."
        )
    if claims.narrated_monologue(message):
        return (
            "not sent: it narrates your own next step ('let me check ...'). "
            "Do the reading first, then send only what they need to know."
        )
    return None


def _unread_evidence_refusal(message: str, claims) -> str | None:
    """The refusal when the draft cites what no tool answered, or None.

    Read against the door's own record of what it answered
    (`outbound.door_readings`), because the gateway's model writes this
    message and the door is the one place its readings pass through, so a
    list of issue numbers and titles that no tool returned cannot go out as a
    board summary. Tier-2 like the other reads here: a window
    that cannot be read is no evidence, and holds nothing up.
    """
    try:
        readings = _outbound.door_readings(_DOOR_READING_WINDOW_SECONDS)
    except Exception as exc:  # noqa: BLE001 - Tier-2: no evidence is not a refusal
        log.warning("could not read the door's readings for an evidence check: %s", exc)
        return None
    window = _DOOR_READING_WINDOW_SECONDS // 60
    unread = claims.unread_issue_numbers(message, _outbound.numbers_read(readings))
    if unread:
        shown = ", ".join(f"#{number}" for number in unread[:8])
        return (
            f"not sent: it cites {shown}, and no tool answer in the last "
            f"{window} minutes held that number. Read the issue (gh_issue_view) "
            "and say what it returned, or leave the number out."
        )
    unread_shas = claims.unread_shas(
        message, tuple(str(reading.get("excerpt", "")) for reading in readings)
    )
    if unread_shas:
        return (
            f"not sent: it cites {', '.join(unread_shas[:8])}, and no tool answer "
            f"in the last {window} minutes held that commit. Read it "
            "(deploy_status or whats_changed), or leave it out."
        )
    if claims.announced_check_never_made(message, len(readings)):
        return (
            "not sent: it says you would check something, and no tool has "
            f"answered in the last {window} minutes. Look first and send what "
            "you found, or say plainly that you have not checked."
        )
    return None


def _all_clear_refusal(message: str, claims) -> str | None:
    """The refusal when the draft says nothing is broken while a paged alert
    still fires, or None.

    Checked whoever the send is booked to, because the brief booked itself to
    The owner on most mornings. Tier-2 like the other reads here: an alerts table
    that cannot be read is no evidence, and holds nothing up.
    """
    try:
        firing = _state.alerts.firing_paged_names()
    except Exception as exc:  # noqa: BLE001 - Tier-2: no evidence is not a refusal
        log.warning("could not read the firing alerts for an all-clear check: %s", exc)
        return None
    found = claims.all_clear_while_firing(message, firing)
    if not found:
        return None
    return (
        f"not sent: {found}. A fault is not old news until it is fixed: name "
        "each one as still down, or leave the all-clear out."
    )


def _repeat_refusal(person: str, number: str, message: str, claims) -> str | None:
    """The refusal when this person already got this message, or None.

    The window is the recent past rather than the whole thread: a question put
    again the next day is a new question, one put again inside the afternoon is
    the same one. Reading the thread is best-effort on purpose, like the write
    at the end of `execute`: a guard that cannot see what was said has no
    evidence of a repeat, and a stored-memory hiccup must never hold up a
    message that is fine.
    """
    try:
        thread = _state.recent_chat_turns(
            number,
            window_seconds=_REPEAT_WINDOW_SECONDS,
            max_turns=_REPEAT_MAX_TURNS,
        )
    except Exception as exc:  # noqa: BLE001 - Tier-2: no evidence is not a refusal
        log.warning("could not read %s thread for a repeat check: %s", person, exc)
        return None
    already_sent = [turn for turn in thread if turn.get("role") == "assistant"]
    repeated = claims.repeated_message(message, already_sent, person)
    return f"not sent: {repeated}" if repeated else None


def _listed_ids(tool_input: dict[str, Any]) -> set[int]:
    """The worklist ids the caller says the message is about, or none.

    Tolerant of what a model writes: a bare id, or ids as strings. Anything
    that is not a whole number is ignored rather than refused, because the
    issue-number match still runs and a malformed list must not hold a send up.
    """
    listed = tool_input.get("worklist_items") or []
    if not isinstance(listed, list):
        listed = [listed]
    ids: set[int] = set()
    for entry in listed:
        try:
            ids.add(int(entry))
        except (TypeError, ValueError):
            continue
    return ids


def _their_items_in(
    person: str, message: str, listed_ids: set[int] = frozenset()
) -> list[dict[str, Any]]:
    """This person's open worklist items that the message actually names.

    Matched on issue number, which is the one token a worklist title and a
    message to a person reliably share. The message side counts a bare number
    too ("catering 47"); the title side still needs an issue spelling, so a bare
    number only matters when it is one of this person's items. Only items this person OWNS are
    considered: the ledger is keyed by item and not by reader, so checking an
    item owned by somebody else would let one telling of it silence the
    telling that goes to the person whose item it is.

    The assistant's OWN items count for every reader too. Since the door
    accepts `requested_by: "the assistant"`, the brief books what nobody asked for to
    the assistant, and a question it raised itself is exactly such an item: matched on owner
    alone, every ask about it would skip this ledger. Nobody's telling of an
    assistant item is silenced by another's, because `_ledger_key` keys it per
    reader.

    An item the caller lists by id in `worklist_items` counts as named too.
    A weekly advisor message can chase an item in words that
    name no issue number; without this the ledger never sees that telling, and the
    item reads as told once when it has been told twice.

    Tier-2: a worklist that cannot be read returns nothing, because no evidence
    of a repeat is not evidence of a repeat, and a guard with no evidence must
    never hold up a message.
    """
    mentioned = {match.group(1) for match in _ISSUE_RE.finditer(message)}
    mentioned |= {match.group(1) for match in _BARE_NUMBER_RE.finditer(message)}
    if not mentioned and not listed_ids:
        return []
    try:
        items = _state.worklist.open_items()
    except Exception as exc:  # noqa: BLE001 - Tier-2: no evidence is not a repeat
        log.warning("could not read the worklist for a repeat check: %s", exc)
        return []
    theirs = [
        item
        for item in items
        if str(item.get("owner", "")).strip().lower()
        in {person.strip().lower(), _ASSISTANT_OWNER}
    ]
    return [
        item
        for item in theirs
        if int(item["id"]) in listed_ids
        or mentioned & {
            match.group(1) for match in _ISSUE_RE.finditer(str(item.get("title", "")))
        }
    ]


def _ledger_key(item: dict[str, Any], person: str) -> str:
    """The ledger key for telling `person` about this worklist item.

    A person's own item is one key whoever reads it, as it always was. A
    The assistant-owned item has no single reader, so each reader gets their own key
    and telling the owner never counts as having told a teammate.
    """
    return _state.reported_items.reader_key(
        int(item["id"]), str(item.get("owner", "")), person
    )


def _candidates_for(items: Sequence[dict[str, Any]], person: str) -> list[Any]:
    """Ledger candidates for those worklist items.

    Fingerprinted on the issue each item names and never on the row's
    `last_finding`: that is a sentence the assistant writes, and the brief may rewrite it
    after every ask about the same item, so each morning the same question
    would read as news. What makes an item sayable again is something only a
    person or the board can do: answer on the issue, tick a box, close the row.
    """
    return [
        _state.reported_items.Candidate(
            item_key=_ledger_key(item, person),
            fingerprint=_state.reported_items.told_fingerprint(
                "open", _title_issue_facts(str(item.get("title", "")))
            ),
        )
        for item in items
    ]


def _title_issue_facts(title: str) -> str:
    """The material facts of every issue a worklist title names, joined."""
    numbers = sorted({match.group(1) for match in _ISSUE_RE.finditer(title)})
    return ";".join(f"{number}={_issue_facts(number)}" for number in numbers)


def _issue_facts(number: str) -> str:
    """One issue's state, comment count and ticked boxes, or "" if unreadable.

    Tier-2, fail-open like every read in this guard: an issue that cannot be
    read gives a different fingerprint from one that could, so the worst a
    GitHub outage does is let one repeat through, never hold a message up.
    """
    try:
        completed = subprocess.run(
            ["gh", "issue", "view", number, "--repo", _REPO,
             "--json", "state,comments,body"],
            capture_output=True, text=True, timeout=_ISSUE_READ_TIMEOUT_S,
        )
        if completed.returncode != 0:
            log.warning("could not read issue %s for a repeat check: %s",
                        number, completed.stderr.strip())
            return ""
        issue = json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        log.warning("could not read issue %s for a repeat check: %s", number, exc)
        return ""
    body = str(issue.get("body") or "")
    ticked = len(_TICKED_BOX_RE.findall(body))
    boxes = ticked + len(_OPEN_BOX_RE.findall(body))
    return f"{issue.get('state')}|{len(issue.get('comments') or [])}|{ticked}/{boxes}"


def _answered_refusal(items: Sequence[dict[str, Any]], person: str) -> str | None:
    """The refusal when the message asks this person about an item they have
    already answered, or None.

    Read off the ledger's `answered_at`, which only `record_answer` writes for
    a conversation, and regardless of the item's fingerprint: an answer does
    not expire because a comment landed on the issue afterwards. The answer
    itself is on the worklist row, and the refusal quotes it so the model uses
    it instead of asking. Telling SOMEBODY ELSE about the item, the answer
    included, is not refused here, because the assistant item's key is per reader.
    """
    by_key = {_ledger_key(item, person): item for item in items}
    if not by_key:
        return None
    answered = _state.reported_items.answered_keys(list(by_key))
    if not answered:
        return None
    item = by_key[sorted(answered)[0]]
    row = _state.worklist.item(int(item["id"])) or {}
    said = str(row.get("answer") or "").strip()
    quoted = f": {said[:160]!r}" if said else ""
    return (
        f"not sent: {person} already answered this "
        f"({str(item.get('title', ''))[:80]}){quoted}. Use their answer; do "
        "not ask them again."
    )


def _already_told_refusal(
    carried: Sequence[Any], items: Sequence[dict], person: str
) -> str | None:
    """The refusal when the message repeats an item that has not moved, or None.

    It names the only exits, both outside the assistant: an answer on the issue, or
    the item closed. Recording a new sentence on the row is not one of them,
    and the refusal must not suggest it is, or the brief takes it at its word.
    """
    if not carried:
        return None
    by_key = {_ledger_key(item, person): item for item in items}
    told = carried[0]
    title = str(by_key.get(told.item_key, {}).get("title", told.item_key))
    return (
        f"not sent: they have already been told this {told.times_reported}x and "
        f"neither the item nor its issue has changed since ({title[:80]}). It "
        "becomes sayable again when they answer on the issue or the item is "
        "closed; until then leave it out, it is on their worklist either way."
    )


def _too_long_refusal(message: str) -> str | None:
    """The refusal when the draft is longer than one Signal message should be,
    or None.

    Arithmetic, not judgement: every other check here can be argued with by a
    draft that reads well, and this one cannot. It names both numbers so one
    rewrite is enough, and it says where the rest belongs rather than only that
    there is too much of it, because a model told "shorter" drops facts and a
    model told "put it on the worklist" moves them.
    """
    words = len(message.split())
    if words <= MAX_MESSAGE_WORDS:
        return None
    return (
        f"not sent: {words} words, and a Signal message may be "
        f"{MAX_MESSAGE_WORDS}. Send the one thing they have to act on and "
        "leave the rest out; if it is worth keeping, it belongs on the "
        "worklist or the issue, not in their phone."
    )


def _wrong_language_refusal(person: str, message: str, claims) -> str | None:
    """The refusal when the draft is not in the language its reader reads, or
    None. Refuses each recipient at most once per turn.

    The detector is cheap and imperfect by design: a false positive costs one
    rewrite and a false negative just lets the message through, so it can never
    drop a message. `claims` is passed in because it is imported lazily at the
    call site (claims reaches write_tools, which imports this module).
    """
    language = people.language_for(person)
    if not language or person.strip().lower() in _language_refused:
        return None
    if not claims.wrong_language(message, language):
        return None
    _language_refused.add(person.strip().lower())
    reads = _LANGUAGE_NAMES.get(language, language)
    return f"not sent: {person} reads {reads}, rewrite and send again."


def _away_refusal(person: str, message: str) -> str | None:
    """The refusal when the draft hands work to someone who is away, or None.

    Only a HANDOVER is refused: telling someone on holiday that the meeting
    moved is fine, giving them a job is not. An `unknown` away-state never
    refuses, it is not evidence they are gone, but it is not evidence they
    are there either, which is what the away block in the prompt is for.
    """
    if not _HANDOVER_RE.search(message):
        return None
    verdict = _person_away.status(person)
    if verdict.state != _person_away.AWAY:
        return None
    return (
        f"not sent: {person} is away until "
        f"{_person_away.human_date(verdict.until)}, put it on your worklist."
    )
