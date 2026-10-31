"""The patrol pass, the assistant on shift, looking around on its own.

Where the morning brief is a
no-tools good-morning, the patrol runs a FEW times a day and is the thing
that makes the assistant feel like a worker rather than a dashboard: each pass it

  1. works its open WORKLIST, checks each watched/looked-into item with
     its read-only tools, records progress, closes what is done, and
     chases answers it is owed;
  2. takes one look around for SLOW-BURN trouble no alert covers, a cost
     creep, a cert a week from expiry, a container quietly restarting, a
     registry ballooning, disk trending up, backups drifting;

and then says AT MOST ONE thing worth the human's attention, an update
on something it is carrying, a fresh observation, or a QUESTION it needs
answered (which it also files on the worklist so it remembers it asked):
or stays QUIET. A bounded read-only tool-loop, plus the
self-writes (`manage_worklist`, `remember_note`) so a pass can update what
it carries and jot what it learns, and the board tool (`github_act`).

A patrol line has exactly ONE destination: the pinned recipient. It is not
addressed mail, so a line that OPENS by addressing somebody else is a line
delivered to the wrong person, for example "Sam, het verslag staat klaar ...
Wil je er even naar kijken?" landing on the owner's phone. `misaddressed_to` is the deterministic
check on that: nudge once, and hold the line if it still opens with someone
else's name. Held is safe here: patrol is allowed to stay QUIET, the finding
stays on the worklist, and the morning brief carries it.

Public callables: `patrol() -> PatrolLine | None` (the plain-text line to
send with the worklist items it opened, or None for QUIET) and
`misaddressed_to(line)`, the addressing predicate.

A LINE CARRIES THE QUESTIONS ITS PASS OPENED. A question patrol
asks is filed on the worklist in the same pass, and a reply closes it only
through `record_answer`, which needs that item's id. So the ids of the
questions the pass opened ride with the line to the chat relay, which names
them to the chat. Only opened questions: a pass also notes progress on items,
and files watch and look_into items as bookkeeping, that its line may never
mention, and naming those would have the chat record a reply against the
wrong item.

EVERY SILENCE IS RECORDED. A pass has four ways to end
with nothing on the wire, and until now all four logged a line and wrote
nothing, so a week in which the beat had nothing to say and a week in which
the model was broken and answered QUIET twenty-one times looked identical in
the data. Each of the four now writes one `outbound.record_quiet` row with the
reason: `pass-faulted` (the loop did not finish: budget tripped, Anthropic
faulted, the cap hit), `misaddressed` (the line opened with somebody else's
name), `quiet-hours` (a line existed and the window was shut), and, at the
convergence point, `model-quiet` or `stripped-to-nothing`.

Those last two are separated by whether `_extract_line` returned a draft at
all, which is honest for the QUIET token and the empty note. It merges one
third route: `_extract_line` also discards a FABRICATED transcript, and that
lands in `model-quiet` although a guard, not the model, made the pass silent.
Telling it apart would mean a second `looks_fabricated` pass over the same
text, and the merge errs toward the far commoner case: QUIET is the documented
normal outcome of most passes, while a fabrication is rare. A `model-quiet` count is therefore a ceiling on genuine model
silence, not an exact one.

The house rule is advisor-not-operator. Reads + its own SQLite artefacts only; no
new IAM surface. Health/structure/metrics, never personal data.

FAILURE POLICY: Tier-2 advisory, budget tripped or Anthropic faulted →
skip this pass (log + None), never a degraded line. QUIET / empty is the
normal "nothing to say". Budget reads/charges are Tier-1.
"""
from __future__ import annotations

from apps.assistant.shared.zone import LOCAL_ZONE

from apps.assistant.shared.name import ASSISTANT_NAME

import dataclasses as _dataclasses
import datetime as _datetime
import logging
import re
from zoneinfo import ZoneInfo

from apps.assistant.core import brain as _brain
from apps.assistant.core import claims
from apps.assistant.core import outbound as _outbound
from apps.assistant.core import page_hold as _page_hold
from apps.assistant.core import people as _people
from apps.assistant.core import quiet_hours as _quiet_hours
from apps.assistant.core import self_context as _self_context
from apps.assistant.core import signal_text
from apps.assistant.core import tools as _tools
from apps.assistant.core.tools import write_tools as _write_tools
from apps.assistant.core.tools.agenda import calendars as _calendars
from apps.assistant.core.limits import PATROL_MAX_ITERATIONS

log = logging.getLogger("openclaw.patrol")

_QUIET_TOKEN = "QUIET"

#: How `manage_worklist` answers a write that opened an item, with its id.
_OPENED_RE = re.compile(r"^tracking as worklist item (\d+)")


@_dataclasses.dataclass(frozen=True)
class PatrolLine:
    """One line a pass released, and the worklist items that pass opened."""

    text: str
    worklist_items: tuple[int, ...] = ()

_SYSTEM_PROMPT = f"""You are {ASSISTANT_NAME}, on shift for the team. This is a
patrol: a few times a day you look around on your own, unprompted. Nobody
asked you anything, you are the colleague at the console who notices things.

Do two things, in order:

Your journal holds your own earlier readings. An explanation in it is an
earlier guess of yours, not a fact: check it before you repeat it.

FIRST, work your open worklist (the "what you are carrying" block above). For
each item: check it with your read-only tools, record what you find with
manage_worklist 'progress', and 'close' anything that is genuinely resolved or
no longer worth watching. If you are owed an answer to a question and it still
matters, that is worth surfacing. A look_into is pursued, not re-read: each
pass either moves it one step toward the cause or hands it off (github_act to
open an issue, or a question for the person who can act), and a restatement of
the symptom is not progress. Test the cause its title names against what you
read now; if the reading contradicts it, close the item and add it again with
the diagnosis you can back.

THEN take one look around for slow-burn trouble that no alert would catch:
a cost creeping up (scw_estimated_monthly_eur is what the fleet listed right
now would cost for a full month, hourly list price times 732 h; it is not
month-to-date and has no billing window, so a step means a resource was added
or removed: find it in the deploys and pools before calling it fine), a TLS
cert within a week of expiry, a container quietly
restarting, the registry ballooning, disk trending up, backups drifting,
a table that stopped growing. Use your read-only tools and the read-only
shell for safe checks (dig, curl -I, openssl s_client for cert dates).

ALSO keep the GitHub board tidy, like a good PA: this is real initiative,
not just noticing. Use gh_issue_list / gh_issue_view to look for board
hygiene, and act with github_act when it is clearly right:
- an OPEN issue with NO assignee is a workflow bug (hard team rule: every
  issue gets an assignee at creation): assign the obvious owner, or if it
  is unclear, ask.
- an issue that is clearly SHIPPED but still open, comment with the
  evidence and close it (always say why in the closing comment).
- a real gap you found on patrol with no issue, open one (always with an
  assignee), so nothing you notice is lost.
- obvious mislabels or a PRD missing its label, fix it.
Everything you do on GitHub is logged and you report it in your morning
brief. Be a careful assistant: only close what is genuinely done, only open
an issue for a real gap, never churn labels, and when a judgement is the
team's, ask instead of acting.

You cannot reach a specific teammate on patrol. Your line goes to ONE
person, the recipient this pass is delivered to, whatever name you write at
the front of it. So never open with somebody else's name: a line that starts
"Sam, ..." lands on the recipient's phone as a message meant for someone
else. If something is for another teammate, put it on your worklist with
manage_worklist and it rides the morning brief. Write in the recipient's own
language.

Then decide what, if anything, to say. You are a PERSONAL ASSISTANT doing
rounds, not a monitor firing alerts. The default is SILENCE: note what you
found on your worklist or journal and stay quiet. Most patrols, the large
majority, should end QUIET. You interrupt a person's day only when they
would genuinely thank you for it.

The bar to send: would a sharp human assistant actually text their boss
about this right now, mid-day, or would they save it for the morning brief?
Save almost everything for the brief. Send now ONLY when it is time-sensitive
or genuinely wants a decision:
- a real question where you are stuck without their call ("the GPU node is still
  pinned and burning ~1 euro/hour, is that the warm-server plan or should I
  scale it down?"). File it with manage_worklist kind='question'.
- something that will cost real money or break if it waits.
A slow creep, a cert with a week left, a registry at 21 tags, those are NOT
mid-day interrupts; note them to your worklist and they ride into the morning
brief. When you DO send, it is one calm colleague line, never an alert.

Never manufacture something to seem busy. Never repeat something you said
recently (your recent messages are in the block above); staying quiet on a
fault that is still broken is fine, because the morning brief names every
one of those until it is fixed. A PA asks ONCE and
then waits: if a question is already on your worklist as asked-and-waiting,
do NOT raise it again, no reminder, no rephrase, unless you have genuinely
new information (it got worse, it resolved, the cost doubled). Waiting
quietly on an answer you already asked for is the correct, assistant-like
move. If in doubt, QUIET.

You may think out loud first. But your ACTUAL message must be wrapped in
<note> and </note>, and ONLY the text inside is sent. Inside: plain text
only (Signal shows markdown literally, no asterisks, backticks, emoji,
bullets, headings, or '---'), in your voice, one or two flowing sentences.
If nothing is worth sending, output exactly <note>QUIET</note>."""

_PATROL_PROMPT = (
    "Do a patrol pass: work your worklist, take one look around, then send "
    "the one line (or QUIET)."
)


# On patrol the assistant carries jobs, jots findings and keeps the board tidy: its
# three write tools. It does NOT teach itself principles (that is a chat-only
# self-write), and it does NOT message teammates: `message_teammate` on an
# autonomous loop is the first path on which the assistant could START a conversation
# with a person who did not message it, so it needs a signed decision
# before it goes on this surface, and none has been made. Declared here by
# NAME; bound in the write registry.
#
# Nothing about the misdelivery described above waits on that signature: the broken
# route was patrol's free-text line being addressed to somebody else, and
# `misaddressed_to` below closes it whether or not the tool is ever added.
_PATROL_WRITE_TOOLS = [
    _write_tools.MANAGE_WORKLIST,
    _write_tools.REMEMBER_NOTE,
    _write_tools.GITHUB_ACT,
]


def _patrol_tool_definitions() -> list[dict]:
    """Read-only surface (minus the triage submit-tool) plus the assistant's two
    self-writes so a pass can update its worklist and journal."""
    return _tools.investigation_definitions() + _write_tools.definitions(_PATROL_WRITE_TOOLS)


_PATROL_ACTOR = _write_tools.Actor(name="assistant", uuid=None, loop="patrol")


def _dispatch(name: str, tool_input: dict, actor: _write_tools.Actor = _PATROL_ACTOR) -> str:
    """Patrol tool dispatch: a write tool bound to the assistant-on-patrol (worklist
    owner + note source + board actor all resolve from `_PATROL_ACTOR`), else
    the read-only registry.

    A write tool this loop did not DECLARE is refused here, not merely left out
    of the definitions: the declared surface is the thing an ADR signs off, so
    it has to be the thing that gates the dispatch too."""
    if _write_tools.is_write_tool(name) and name not in _PATROL_WRITE_TOOLS:
        return f"refused: {name} is not one of your patrol tools."
    written = _write_tools.dispatch(name, tool_input, actor)
    return written if written is not None else _tools.execute(name, tool_input)


# How a person is addressed at the FRONT of a line, in either language:
# "Sam, ...", "Hoi Sam -", "Alex: ...". Only the opening counts; a line
# that MENTIONS a teammate ("Sam pushed a fix") is about them, not to them,
# and is fine to send to the recipient.
_GREETING = r"(?:hoi|hi|hey|hallo|dag|beste|goedemorgen|good morning|morning)"


# Second-person address, Dutch and English. This is what separates a line
# ABOUT a teammate ("Sam pushed a fix") from a line TO one ("Sam, wil je even
# kijken?"). Only the second is a misaddressed message; the first is exactly
# what a patrol note is for, so keying on the name alone would silence the beat.
_SECOND_PERSON_RE = re.compile(
    r"\b(?:je|jij|jou|jouw|jullie|u|your|yours|you)\b", re.IGNORECASE
)

# Ways a note opens by addressing someone. Wider than a leading name plus a
# comma, because trivial rephrasings walk straight past that ("Sam het verslag
# staat klaar", "@Sam ...", "Voor Sam: ...", "Sam? ..."). The name may carry an @, may be
# introduced by a preposition, and may be followed by any punctuation or simply
# by more sentence.
_ADDRESS_PREFIX = r"(?:voor|for|aan|to|hey|hi|hallo|hoi|beste|dear)"


def _addressed_name(line: str) -> str | None:
    """The teammate the line addresses rather than talks about, or None.

    Two shapes count. The line opens with their name, however it is punctuated
    and whether or not an @ or a preposition leads it; or the line names them
    anywhere and then speaks in the second person, which is a message to them
    wearing a sentence about them. Names come from the people registry, which
    is the only place that says who exists."""
    second_person = bool(_SECOND_PERSON_RE.search(line))
    for name in _people.names():
        escaped = re.escape(name)
        # A possessive is always talking about them: "a teammate's DPA request".
        possessive = re.compile(rf"\b{escaped}(?:'s|s'|')", re.IGNORECASE)
        opening = re.compile(
            rf"^\s*(?:{_GREETING}\s+)?(?:{_ADDRESS_PREFIX}\s+)?@?{escaped}\b(?!'s)"
            r"\s*(?P<punct>[,:!?.-])?",
            re.IGNORECASE,
        )
        match = opening.search(line)
        if match and not possessive.match(line.strip()):
            # Opening with their name is vocative when punctuation follows it
            # ("Sam, ...", "Sam? ...", "Voor Sam: ..."), or when the note
            # goes on to speak in the second person ("Sam het verslag staat
            # klaar, wil je kijken?"). Opening with their name and carrying
            # straight on in the third person is a sentence ABOUT them
            # ("Sam pushed a fix"), which is what a patrol note is for.
            if match.group("punct") or second_person:
                return name
        if second_person and re.search(rf"@{escaped}\b|\b{escaped}\b", line, re.IGNORECASE):
            return name
    return None


def _reader() -> _people.Person | None:
    """The person this pass's line will be delivered to, or None when the
    pinned recipient resolves to nobody in the registry. The beats know a phone
    number and no Signal UUID, so this uses the weak by-number lookup."""
    destination = _outbound.recipient()
    if not destination:
        return None
    return _people.identify_by_number(destination)


def _reader_language() -> str | None:
    """Which language the recipient reads ("nl"/"en"), or None when the
    registry does not say. Same resolution as the morning brief's."""
    reader = _reader()
    return _people.language_for(reader.name) if reader is not None else None


def misaddressed_to(line: str) -> str | None:
    """The teammate a line opens by addressing when they are NOT the person it
    will be delivered to, else None.

    A recipient the registry cannot resolve counts as not-the-addressee: an
    addressee nobody confirmed is not a confirmed one, and holding a line costs
    far less than putting one person's message on another person's phone.
    """
    addressee = _addressed_name(line)
    if addressee is None:
        return None
    reader = _reader()
    if reader is not None and reader.name.strip().lower() == addressee.strip().lower():
        return None
    return addressee


def _misaddressed_nudge(addressee: str, reader_name: str | None) -> str:
    reader = reader_name or "the recipient"
    return (
        "[automatic check, NOT from the person] Your line opens by addressing "
        f"{addressee}, but a patrol line has one destination and it is "
        f"{reader}: whatever you write here lands on {reader}'s phone, not "
        f"{addressee}'s. You cannot reach {addressee} from a patrol pass. "
        f"Either write the line for {reader}, speaking about {addressee} "
        "rather than to them, or put it on your worklist with manage_worklist "
        "so it rides the morning brief and output <note>QUIET</note>. Do NOT "
        "mention this note; reply as if it never appeared."
    )


def _extract_line(response) -> str | None:
    """The patrol's plain-text line from a final response, or None for
    QUIET / empty / a fabricated transcript."""
    raw = signal_text.text_of(response)
    if signal_text.looks_fabricated(raw):
        log.warning("patrol produced a fabricated transcript; staying QUIET")
        return None
    note = signal_text.strip_markdown(signal_text.extract_note(raw))
    if not note or signal_text.is_sentinel(note, _QUIET_TOKEN):
        return None
    return note


def _overnight(line: str, now: _datetime.datetime | None = None) -> str:
    """Say when a held line was seen, in the reader's own clock.

    A line written at 23:06 and read at 09:00 is a different sentence, and
    without the hour there is nothing in it to tell the reader which one they
    are holding. The clock is local because the reader is; the
    stamp goes in front because the reader should know it is history before
    they read the claim, not after.
    """
    moment = now or _datetime.datetime.now(LOCAL_ZONE)
    return f"Overnight, {moment:%H:%M}: {line}"


def patrol() -> PatrolLine | None:
    """Run one patrol pass. Returns the line to send, or None for QUIET /
    skipped."""
    messages: list[dict] = [{"role": "user", "content": _PATROL_PROMPT}]
    succeeded: set[str] = set()
    # Reads that actually returned data this pass, an UNAVAILABLE or FAILED
    # render is not evidence (same receipt-counting as chat). Board
    # reads counted separately for the board-statement gate.
    reads = {"ok": 0, "board": 0}
    seen_issue_numbers: set[int] = set()
    # The questions this pass opened, which its line asks.
    opened: list[int] = []
    # What the pass actually READ, kept rather than counted. The
    # counters above answer "did you look" but not what was seen; without the text, a
    # beat could not be checked against its own readings an hour later.
    readings: list[_outbound.Reading] = []

    def _evidence() -> list[str]:
        """What this pass read, for checking its own notes: a read
        that answered, or a write whose answer is news."""
        return [
            reading.excerpt
            for reading in readings
            if reading.outcome == "ok"
            or (reading.outcome == "wrote" and not _write_tools.echoes_its_input(reading.tool))
        ]

    actor = _dataclasses.replace(_PATROL_ACTOR, evidence=_evidence)

    def _dispatch_tracked(name: str, tool_input: dict) -> str:
        result_text = _dispatch(name, tool_input, actor)
        outcome = "other"
        if _write_tools.was_success(name, result_text):
            outcome = "wrote"
            succeeded.add(name)
            if name == _write_tools.GITHUB_ACT:
                reads["board"] += 1
                seen_issue_numbers.update(claims.issue_numbers_in(result_text))
            opened_item = _OPENED_RE.match(result_text.lstrip())
            # Only a question is something a reply answers; a watch or
            # look_into item the pass filed is bookkeeping its line may not name.
            is_question = tool_input.get("kind") == "question"
            if name == _write_tools.MANAGE_WORKLIST and opened_item and is_question:
                opened.append(int(opened_item.group(1)))
        elif not _write_tools.is_write_tool(name) and not result_text.startswith(
            ("UNAVAILABLE", "FAILED", "unknown tool")
        ):
            # Only a READ counts as evidence, and a write tool this loop does
            # not carry is refused above rather than run, so its refusal must
            # not be counted either.
            outcome = "ok"
            reads["ok"] += 1
            if name.startswith("gh_"):
                reads["board"] += 1
                seen_issue_numbers.update(claims.issue_numbers_in(result_text))
        elif result_text.startswith(("UNAVAILABLE", "FAILED", "unknown tool")):
            # Stripped of its punctuation so the vocabulary is a closed set:
            # the renders are "UNAVAILABLE: ..." and "FAILED: ...", and an
            # outcome of "unavailable:" is a word nothing can be compared to.
            outcome = result_text.split(None, 1)[0].rstrip(":").lower()
        readings.append(_outbound.Reading.of(name, tool_input, outcome, result_text))
        return result_text

    nudged = {"done": False}

    def _on_text(response) -> str | None:
        """Receipts: a patrol line that claims a board action it never made (no
        successful github_act) is a lie, nudge once to do it or drop the claim.
        No human request here, so require_request=False. Fabricated / QUIET /
        empty just stops (handled by `_extract_line`). The same single nudge
        also covers the did-you-LOOK gate: a line naming a cause or a
        count with zero successful reads this pass, a line addressed to someone
        who will never receive it, and a line in the wrong language."""
        if nudged["done"]:
            return None
        line = _extract_line(response)
        # The note as the model wrote it. `_extract_line` has already run the
        # deterministic strip, so a command handed to the reader is gone from
        # `line` and a line that was ONLY a hand-off arrives here as None; the
        # command guard has to see the draft to ask for the result instead.
        note = signal_text.extract_note(signal_text.text_of(response))
        if line is None:
            if signal_text.is_sentinel(note, _QUIET_TOKEN) or signal_text.looks_fabricated(note):
                return None  # QUIET and fabrications are nothing to ask about
            nudge = claims.command_syntax(note)
            if nudge:
                log.warning("patrol line was only a hand-off; nudging")
                nudged["done"] = True
                return nudge
            return None
        # Delivery first: a line for the wrong person is wrong however honest
        # its content is, and it is the one defect that reaches a third party.
        addressee = misaddressed_to(line)
        nudge = None
        if addressee:
            reader = _reader()
            nudge = _misaddressed_nudge(addressee, reader.name if reader else None)
        if not nudge:
            nudge = claims.unbacked_write_claim(
                line, [], succeeded, set(_PATROL_WRITE_TOOLS), require_request=False
            )
        if not nudge:
            nudge = claims.unbacked_causal_claim(line, reads["ok"])
        if not nudge:
            # The same question from the other end: not "was that read" but
            # "was the check you announced actually made". A beat speaks
            # unprompted three times a day, so a line promising a look it never
            # took leaves the reader waiting for a second half that never comes.
            nudge = claims.announced_check_never_made(line, reads["ok"])
        if not nudge:
            # Two claims no amount of reading can back, so they sit outside the
            # read-count gate above rather than inside it.
            nudge = claims.reader_action_claim(line)
        if not nudge:
            nudge = claims.forecast_claim(line)
        if not nudge:
            nudge = claims.unbacked_board_statement(line, reads["board"])
        if not nudge:
            nudge = claims.fabricated_issue_numbers(line, seen_issue_numbers)
        if not nudge:
            today = _datetime.datetime.now(LOCAL_ZONE).date()
            nudge = claims.wrong_weekday(line, today)
        if not nudge:
            # A green readout is not news on an UNSOLICITED beat: "all 11 up,
            # disk 41%" buys a phone buzz with nothing to act on. The brief's
            # guard carries over here for that reason and NOT to chat, where a
            # healthy number is often the answer to the question asked. Nudge
            # only, never a strip: patrol may go quiet, so a nudge costs one
            # re-prompt and nothing else.
            nudge = claims.green_telemetry(line)
        if not nudge:
            # A commit sha, how an alert was routed, how many components were
            # counted: all true, none of it anything the reader acts on. The
            # brief has carried this guard since an issue and patrol never did,
            # although patrol is the loop that READS deploy state and so the
            # one most likely to recite it. An acceptance rule asks that no
            # rendered message carry a commit sha, and this is where patrol's
            # half of that is enforced.
            nudge = claims.own_plumbing(line)
        if not nudge:
            # Presentation, not grounding (the house rules leave a
            # tool-using loop free to assert a new problem): say what you
            # found, do not hand the reader the command.
            nudge = claims.command_syntax(note)
        if not nudge:
            # Patrol fires three times a day onto the same phone, and nothing
            # downstream renders per language: the seams that DO (the meeting
            # reminder, message_teammate) are not on this path.
            nudge = claims.wrong_language(line, _reader_language())
        if nudge:
            log.warning("patrol line tripped an honesty guard; nudging")
            nudged["done"] = True
            return nudge
        return None

    # Nobody is speaking on a patrol pass, so `agenda_view` must not still be
    # answering as whoever last chatted. The speaker is module state for one
    # turn, and agenda_view is on this loop's surface, so clearing it here is
    # what stops a private calendar being read into an autonomous pass.
    _calendars.set_speaker(None)
    # Spine + worklist + this loop's task, assembled once in `self_context`;
    # patrol now also gets the current-picture block (the date) it lacked.
    system = _self_context.render("patrol", _SYSTEM_PROMPT)
    outcome = _brain.run(
        system=system,
        messages=messages,
        tools=_patrol_tool_definitions(),
        cap=PATROL_MAX_ITERATIONS,
        dispatch=_dispatch_tracked,
        on_text=_on_text,
        recheck_budget=True,
    )
    # Advisory: budget tripped, Anthropic faulted, or the cap hit all skip the
    # pass silently. Only a `finished` pass can yield a line.
    if not outcome.finished:
        log.info("patrol pass produced no line (%s); skipping", outcome.status)
        _outbound.record_quiet("patrol", "pass-faulted")
        return None
    line = _extract_line(outcome.response)
    # The draft as the model left it, kept because it is the only thing that
    # tells the two silences below apart once the strips have run.
    draft = line
    if line is not None and reads["ok"] == 0 and claims.unbacked_causal_claim(line, 0):
        # Nudged and still diagnosing with nothing read: send the symptom,
        # drop the causal sentence, or go QUIET if nothing survives.
        line = claims.strip_causal_sentences(line) or None
    if line is not None:
        # Nudged and still crediting the reader with an action, or still
        # predicting. Both are stripped whatever the read count, because
        # neither becomes true if the pass reads harder: the assistant cannot see what
        # a person does on that box, and a rate drawn through a series that
        # swings is not a measurement.
        #
        # The shape: a line crediting a reader with an action ("after your
        # cleanup") or forecasting one ("will need another cleanup tonight")
        # that the pass never observed. Both sentences go, and if that leaves
        # nothing then nothing is what patrol says, which is a thing it is
        # allowed to do.
        line = claims.strip_reader_action_claims(line) or None
    if line is not None:
        line = claims.strip_forecasts(line) or None
    if line is not None and claims.green_telemetry(line):
        # Nudged and still reading out healthy numbers. Every other guard on
        # this road strips after the loop, and this one does too, or a second
        # draft that kept the readout would go out whole. Safe here for the same reason the strips above are: patrol may say
        # nothing, so a line that is only a green readout becoming nothing is
        # the right outcome rather than a suppressed report.
        line = claims.strip_green_telemetry(line) or None
    if line is not None and claims.own_plumbing(line):
        # Nudged and still reporting openclaw's own bookkeeping. Same shape,
        # same reason.
        line = claims.strip_own_plumbing(line) or None
    if line is not None:
        # Nudged and still opening with somebody else's name: the line is held.
        # Stripping the name would only hide the problem, because the sentences
        # after it are still written TO that person ("wil je er even naar
        # kijken?"), and patrol is allowed to say nothing, so nothing is what
        # it says. The
        # finding stays on the worklist and rides the morning brief.
        addressee = misaddressed_to(line)
        if addressee:
            log.warning(
                "patrol line was addressed to %s, not the recipient; holding it: %r",
                addressee,
                line[:80],
            )
            _outbound.record_quiet("patrol", "misaddressed")
            return None
    if line is not None and _quiet_hours.quiet_now():
        # Quiet hours: a patrol line is by definition unsolicited, and
        # nothing patrol says is page-urgent (real pages take the paging path).
        # So it does not go out now.
        #
        # HELD, NOT DROPPED. Returning here having written the line nowhere
        # leaves the finding two possible fates, both wrong: the condition
        # clears before morning and nobody is ever told it happened, or it is
        # still findable and the next pass reports it as present news about a
        # container that has long been back up.
        #
        # `hold_beat`
        # is where a held beat waits, and `page_hold.release` carries it
        # out with the morning brief on a weekday and on its own at
        # `ASSISTANT_MORNING_GATE_UNTIL` at a weekend, which is exactly what an
        # overnight finding wants.
        #
        # Stamped with the hour it was SEEN, because the whole failure above is
        # a night reading read in the morning as the present tense. Saying when
        # cannot make that mistake. It does not say whether the thing is still
        # true: the pass that runs after the gate opens answers that, freshly,
        # and the two lines together are the honest version.
        _page_hold.hold_beat(
            _overnight(line), subject="patrol", road="patrol", worklist_items=tuple(opened)
        )
        log.info("patrol line held for the morning: %r", line[:80])
        _outbound.record_quiet("patrol", "quiet-hours-held")
        return None
    if line is None:
        # A pass that said nothing used to write nothing. There is still no
        # message for the readings to be evidence FOR, so no `message_evidence`
        # row is written here; what is written is the audit row saying the pass
        # happened and chose silence.
        #
        # Two routes converge here and `draft` separates them: None means the
        # model itself said QUIET, a string means the model spoke and the strips
        # above left nothing of it.
        _outbound.record_quiet(
            "patrol", "model-quiet" if draft is None else "stripped-to-nothing"
        )
        return None
    # Recorded AFTER every strip and after the quiet-hours hold, so the row
    # holds the text that was actually released and not the draft the model
    # wrote. What this records is what patrol RELEASED, not what Signal
    # accepted: the gate does the sending (`gates/app._webhook_patrol`), and
    # whether a message arrived is a separate audit (`outbound.record_delivery`).
    _outbound.remember_readings("patrol", line, readings)
    return PatrolLine(text=line, worklist_items=tuple(opened))
