"""Receipts guard, shared by chat, patrol and every paging loop.

A model can say "Done, set for tomorrow" or "I asked a teammate" without ever
calling the tool, which ships a confident lie. The fix is one rule, in one
place: a draft that CLAIMS a write action was done is only allowed through
if a matching write tool actually SUCCEEDED this turn (see
`write_tools.was_success`). Otherwise the loop nudges the model once to do
it for real or take the claim back.

`unbacked_write_claim(answer, context_texts, succeeded, available_tools,
require_request) -> str | None` returns the nudge to inject, or None when
the draft is honest. It is category-based: calendar (`agenda_act`), teammate
message (`message_teammate`), and board (`github_act`). Only a category the
loop can actually act on (its `available_tools`) is ever checked, so a loop
is never nudged about a tool it does not have.

`require_request` gates chat: the claim guard only fires when the person
actually asked for that action, so a "who are you" reply that merely
describes what the assistant can do never trips it. Patrol has no human request, so
it passes `require_request=False`, a patrol claim of a board action with no
successful `github_act` is wrong on its own.

The no-tools brief has three more, all in the same shape (nudge once,
strip mechanically, never block): `unsupported_liveness` /
`strip_unsupported_liveness` check every state claim against the grounded
blocks the caller assembled (the evidence bundle, plus the change feed, the
carried items and the support inbox when the caller passes them),
`green_telemetry` / `strip_green_telemetry` drop healthy-number readouts
nobody acts on, and `wrong_language` catches a message written in the language
the recipient does not read.

Two of those are presentation rules rather than grounding rules, so they also
run where a loop HAS tools (the house rules leave such a loop free to
assert a new problem, and neither of these asks whether it checked anything).
`green_telemetry` nudges on patrol, which speaks unasked like the brief; chat
does not carry it, because a green reading is often the answer to the question
asked. `command_syntax` nudges on chat and patrol: `core.voice` forbids writing
a command for the reader to run, and the nudge runs ahead of the deterministic
strip in `signal_text.strip_markdown` so the strip rarely has to cut a
sentence.

FAILURE POLICY: pure text predicates, no I/O. A miss (false negative) just
lets a draft through; the guard is a safety net, not a gate.
"""
from __future__ import annotations

from apps.assistant.shared.zone import LOCAL_ZONE

import datetime as _dt
import re
from dataclasses import dataclass
from typing import Callable, Mapping, Protocol, Sequence
from zoneinfo import ZoneInfo

from apps.assistant.core import signal_text as _signal_text
from apps.assistant.core.tools import write_tools as _write_tools

# ── calendar ──────────────────────────────────────────────────────────────
_CAL_DONE_RE = re.compile(
    # `moved`, `updated` and their Dutch twins are here, and the ORDER matters: `write_tools._SUCCESS_PREFIXES` had to recognise the
    # "moved " and "updated " receipts first. Widening this regex while a
    # landed move still counted as no write would have turned every successful
    # move into a false nudge, which is the guard accusing the assistant of making up
    # work it really did.
    r"\b(added|set (it|them|for)|put (it|that)|booked|scheduled|planned|created|"
    r"moved|updated|toegevoegd|geregeld|verplaatst|verzet|bijgewerkt|aangepast|"
    r"removed|deleted|verwijderd|done|weg)\b"
    r"|\bit'?s (in|on) (the |your )?(agenda|calendar|team_calendar)\b"
    r"|\bstaat (in|erin)\b",
    re.IGNORECASE,
)
_CAL_CONTEXT_RE = re.compile(
    r"\b(agenda|calendar|team_calendar|event|afspraak|meeting|teamcheck|briefing|sync test|lunch)\b"
    r"|\b\d{1,2}[:.h]\d{2}\b"
    r"|\b(tomorrow|today|morgen|vandaag|monday|tuesday|wednesday|thursday|friday|saturday|sunday"
    r"|maandag|dinsdag|woensdag|donderdag|vrijdag|zaterdag|zondag)\b",
    re.IGNORECASE,
)
_CAL_OFFER_RE = re.compile(
    r"\b(want me to|shall i|should i|do you want|can i add|zal ik|wil je dat)\b", re.IGNORECASE
)
_CAL_REQUEST_RE = re.compile(
    r"\b(add|remove|delete|cancel|clear|schedule|re-?schedule|book|move|put|plan|"
    r"zet|verwijder|verplaats|annuleer|boek|inplannen|verzet)\b",
    re.IGNORECASE,
)

# ── teammate message ──────────────────────────────────────────────────────
def _team_names_alternation() -> str:
    """The people registry's names as regex alternatives, read once at import
    so a teammate addressed by name counts like a pronoun does. A leading
    `|` keeps the pattern valid with an empty registry."""
    from apps.assistant.core import people  # lazy: avoid core-init cycle

    return "".join("|" + re.escape(name.lower()) for name in people.names())


_TEAM_NAMES = _team_names_alternation()

_PERSON_RE = re.compile(
    r"\b(hem|haar|them|ze|hen|teammate|collega|colleague" + _TEAM_NAMES + r")\b",
    re.IGNORECASE,
)
_MSG_DONE_RE = re.compile(
    r"\b(messaged|texted|told|asked|pinged|notified|sent|let .{0,20}? know|"
    r"bericht (gestuurd|verstuurd)|gestuurd|doorgegeven|laten weten|gevraagd|geappt)\b",
    re.IGNORECASE,
)
_MSG_REQUEST_RE = re.compile(
    r"\b(tell|ask|message|ping|notify|let .{0,20}? know|remind|"
    r"stuur|vraag|bericht|laat .{0,20}? weten|herinner|geef .{0,20}? door)\b",
    re.IGNORECASE,
)

# ── board (GitHub) ────────────────────────────────────────────────────────
_GH_CONTEXT_RE = re.compile(r"\b(issue|ticket|board|pr|#\d+)\b", re.IGNORECASE)
_GH_DONE_RE = re.compile(
    r"\b(closed|opened|reopened|created|filed|assigned|labell?ed|commented|"
    r"gesloten|aangemaakt|heropend|toegewezen|gelabeld|becommentarieerd)\b",
    re.IGNORECASE,
)
_GH_REQUEST_RE = re.compile(
    r"\b(close|open|reopen|create|file|assign|label|comment|"
    r"sluit|maak|heropen|wijs .{0,20}? toe|label|reageer)\b",
    re.IGNORECASE,
)


# ── memory (journal / principle / rule / bible) ───────────────────────────
# Conservative: only unambiguous "I stored it" phrasings, so a plain
# observation ("I noted the shop is green") is not read as a memory-write claim.
_MEM_DONE_RE = re.compile(
    r"\b(noted (it|that|this) down|written (it|that) down|made a note of|"
    r"saved (it|that)|recorded (it|that)|i'?ll remember (it|that|this)|i'?ve remembered|"
    r"added (it|that) to (my )?(memory|notes|journal|bible)|"
    r"genoteerd|opgeslagen|opgeschreven|vastgelegd|onthouden|"
    r"in mijn (geheugen|bijbel) (gezet|opgeslagen))\b",
    re.IGNORECASE,
)
_MEM_REQUEST_RE = re.compile(
    r"\b(remember (this|that|it)|note (this|that|it) down|save (this|that|it)|"
    r"write (this|that|it) down|keep (this|that|it) in mind|make a note|"
    r"onthoud|noteer|sla .{0,12}? op|schrijf .{0,12}? op|leg .{0,12}? vast)\b",
    re.IGNORECASE,
)

# ── worklist ──────────────────────────────────────────────────────────────
_WL_DONE_RE = re.compile(
    r"\b(added (it|that) to (my )?(worklist|list)|i'?m (tracking|watching) (it|that|this)|"
    r"i'?ll (track|watch|keep an eye on) (it|that|this)|(it'?s|that'?s) on my (worklist|list)|"
    r"op mijn (lijst|worklist) (gezet|staat)|houd ik (in de gaten|bij)|zet ik op mijn lijst)\b",
    re.IGNORECASE,
)
_WL_REQUEST_RE = re.compile(
    r"\b(keep an eye on|watch (this|that|it)|track (this|that|it)|look into (this|that|it)|"
    r"follow up on|houd .{0,15}? in de gaten|volg .{0,15}? op|hou .{0,15}? bij)\b",
    re.IGNORECASE,
)




@dataclass(frozen=True)
class _Category:
    action: str          # plain phrase for the nudge ("change the calendar")
    tools: tuple[str, ...]           # the tool(s) that back this claim (any one)
    claim: Callable[..., bool]       # the draft claims this was done
    request: Callable[[str], bool]   # the context asked for it


def _cal_claim(answer: str, context: str = "") -> bool:
    """A terse confirmation counts too.

    Demanding a calendar word in the ANSWER would let "Done, both removed."
    score False in every category and sail past the guard, and that is
    exactly the phrasing a model uses for a removal it has not made. The
    context word may come from the conversation instead: the
    person said which calendar they meant, and the answer need not repeat it.
    The request check still reads the PERSON's words only, so this cannot
    self-trip on the assistant's own "I can add events".
    """
    return bool(
        _CAL_DONE_RE.search(answer)
        and (_CAL_CONTEXT_RE.search(answer) or _CAL_CONTEXT_RE.search(context))
        and not _CAL_OFFER_RE.search(answer)
    )


_CATEGORIES: tuple[_Category, ...] = (
    _Category(
        action="change the calendar",
        tools=(_write_tools.AGENDA_ACT,),
        claim=_cal_claim,
        request=lambda blob: bool(_CAL_REQUEST_RE.search(blob) and _CAL_CONTEXT_RE.search(blob)),
    ),
    _Category(
        action="message a teammate",
        tools=(_write_tools.MESSAGE_TEAMMATE,),
        claim=lambda a: bool(_MSG_DONE_RE.search(a) and _PERSON_RE.search(a)),
        request=lambda blob: bool(_MSG_REQUEST_RE.search(blob) and _PERSON_RE.search(blob)),
    ),
    _Category(
        action="change the board",
        tools=(_write_tools.GITHUB_ACT,),
        claim=lambda a: bool(_GH_DONE_RE.search(a) and _GH_CONTEXT_RE.search(a)),
        request=lambda blob: bool(_GH_REQUEST_RE.search(blob) and _GH_CONTEXT_RE.search(blob)),
    ),
    _Category(
        action="save it to your memory",
        # any of the memory-writes backs "I saved that": note, principle, rule
        tools=(_write_tools.REMEMBER_NOTE, _write_tools.REMEMBER_PRINCIPLE,
               _write_tools.PERSONAL_RULE),
        claim=lambda a: bool(_MEM_DONE_RE.search(a)),
        request=lambda blob: bool(_MEM_REQUEST_RE.search(blob)),
    ),
    _Category(
        action="track it on your worklist",
        tools=(_write_tools.MANAGE_WORKLIST,),
        claim=lambda a: bool(_WL_DONE_RE.search(a)),
        request=lambda blob: bool(_WL_REQUEST_RE.search(blob)),
    ),
)


def _nudge(cat: _Category) -> str:
    tool = cat.tools[0]
    return (
        f"[automatic check, NOT from the person] Your draft claims you did something you can "
        f"only do by calling {tool} (or a sibling tool), but you made no successful such call "
        f"this turn. If they asked you to {cat.action} and you have not done it, call the tool "
        f"now to do it for real. Otherwise just answer the person naturally. Either way, do NOT "
        f"mention this note, this check, or that anything was verified, reply as if it never appeared."
    )






# "both", "all three", "allebei": a claim about MORE THAN ONE write. One
# successful call cannot back it, or "Done, both removed." would pass while
# only one event had actually been removed.
_PLURAL_CLAIM_RE = re.compile(
    r"\b(both|all (of them|three|four)?|each|every one|the two|"
    r"beide|allebei|alle drie|allemaal)\b",
    re.IGNORECASE,
)


def _claimed_count(answer: str) -> int:
    """How many writes the draft claims: 2 when it says "both", else 1."""
    return 2 if _PLURAL_CLAIM_RE.search(answer) else 1


def unbacked_write_claim(
    answer: str,
    context_texts: list[str],
    succeeded,
    available_tools: set[str],
    require_request: bool = True,
) -> str | None:
    """The nudge to inject if `answer` claims a write that no successful tool
    backs this turn, or None when the draft is honest. Only categories whose
    tool is in `available_tools` are considered.

    The claim is read from `answer` (what the assistant drafted); the request is read
    from `context_texts` (the PERSON's words) ONLY, never from the answer, or
    The assistant's own "I can add events" would read as a request and self-trip."""
    blob = " ".join(context_texts)
    # `succeeded` may be a set of tool names (legacy) or a list of receipts,
    # one entry per successful call. The list form is what lets a plural claim
    # require more than one backing call.
    receipts = list(succeeded)
    for cat in _CATEGORIES:
        backing = [tool for tool in cat.tools if tool in available_tools]
        if not backing:
            continue  # this loop cannot act on this category at all
        landed = sum(1 for name in receipts if name in backing)
        if not _claims_this(cat, answer, blob):
            continue
        if require_request and not cat.request(blob):
            continue
        # A set collapses repeats, so counting only bites with receipts; with a
        # set this stays the old "any backing write landed" behaviour.
        if landed >= _claimed_count(answer):
            continue
        return _nudge(cat)
    return None


def _claims_this(cat: _Category, answer: str, context: str) -> bool:
    """Run a category's claim check, passing context to those that accept it."""
    try:
        return bool(cat.claim(answer, context))
    except TypeError:
        return bool(cat.claim(answer))


# ── causal and quantitative claims ─────────────────────
# The write guard above asks "did you DO this?". This one asks "did you LOOK?".
# A confident wrong diagnosis has a typical shape: a cause, a count or a
# duration asserted without a successful read that turn.
#
# Deliberately conservative: this fires ONLY when the turn contains no
# successful read at all. If the assistant looked at anything, it is not nudged, so a
# partially-researched answer is left alone. Unlike the write nudge, the worst
# case here is one extra read-only call, never an unrequested write.
_CAUSAL_CLAIM_RE = re.compile(
    r"\b(because|caused by|the cause (is|was)|root cause|due to|that'?s why|"
    r"it turns out|comes from|stems from|"
    # A diagnosis in this register, "a 403 means ..., which usually points to
    # a registration problem", matches none of the plain-causal words above.
    # Diagnosis verbs, kept narrow
    # (hedged-adverb or number-subject forms) so factual "points to" prose
    # ("the DSN points to the research DB") stays clean.
    r"(usually|likely|probably|typically|often) (points? to|means|indicates|suggests)|"
    r"\d+ (error )?means|(indicates|suggests) that|"
    # A page none of the above matches: "the alert points at
    # harness-textfile.service as the likely cause (crashed or stopped)". A
    # hedging adjective in front of "cause" is still naming a cause, and such a
    # page can carry a restart instruction for a unit that is running fine.
    # This sentence is in the fixtures.
    r"(likely|probable|possible|apparent|suspected|probably the) cause|"
    r"points? (at|to) [^,.]+ as (the|a) |"
    r"\bblames?\b|"
    # A diagnosis by analogy to memory: "Same GPU driver-upgrade timing issue
    # as last week" and "Same pattern as the earlier
    # incidents" name a cause no read of that turn shows.
    r"same (?:[\w/]+[\s-]+){0,4}(?:issue|pattern|problem|cause|failure) as|"
    r"known (?:issue|problem|blind spot)|"
    r"omdat|de oorzaak|komt door|daarom)\b",
    re.IGNORECASE,
)
# THE PERCENT SIGN SITS OUTSIDE THE WORD-BOUNDARY GROUP, and it has to.
# Inside, the pattern would read `(%|percent|...)\b`, and `\b` after a literal
# `%` can only match when a WORD character follows it. In prose a percentage
# is followed by a space, a comma or a full stop, so that branch would match
# "30%x" and nothing a person would ever write, and every percentage claim
# would walk past the did-you-actually-look gate. `_PERCENT_RE` below follows
# the same rule.
_QUANTITY_CLAIM_RE = re.compile(
    r"\b\d+\s*(?:%|(?:percent|errors?|failures?|restarts?|times|hours?|days?|"
    r"minutes?|weeks?|months?|GB|MB|requests?|pods?|commits?|uur|dagen|keer)\b)"
    r"|\bsince \d{4}-\d{2}-\d{2}\b"
    r"|\b(?:every|elke) (?:night|day|hour|nacht|dag|uur)\b",
    re.IGNORECASE,
)
# Saying you have NOT checked is the honest move this guard wants to encourage,
# so never nudge a draft that already admits it.
_HEDGE_RE = re.compile(
    r"\b(i (have not|haven'?t|did not|didn'?t) (checked|looked|verified)|"
    r"i can'?t (check|verify|see)|not verified|unverified|i'?m not sure|"
    r"cannot confirm|can'?t confirm|no way to (check|see)|unavailable)\b",
    re.IGNORECASE,
)


# Words too common to prove anything. A causal sentence that overlaps the tool
# output only on these is not grounded in it.
_COMMON_WORDS = frozenset(
    """that this with from have has been were was will would could should
    there their they them then than when what which while your yours about
    into over under after before because since also just only same other
    more most much many some such very still again both each between
    during without within through against among able like make made
    take taken give given need needs want wants look looks looked
    check checks checked found find finds does done doing
    the and for but not you are its it's how why who whom whose""".split()
)
# Split on word boundaries AND camel case, so "MemoryError" is memory + error
# and "24 GiB" is 24 + gib. Matching raw words missed that
# "hit its 24 GiB memory limit" is backed by "MemoryError: cannot allocate
# 24 GiB", which is exactly the kind of diagnosis we want to keep.
_TOKEN_RE = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")
# A shared term only proves something if it is substantial: five letters or a
# number. Sharing "the" or "has" proves nothing, and a guard that accepts it
# passes everything.
_MIN_TOKEN = 5


def _distinctive_tokens(text: str) -> set[str]:
    """The terms in `text` specific enough that sharing one means something."""
    tokens = set()
    for match in _TOKEN_RE.findall(str(text or "")):
        lowered = match.lower()
        if lowered in _COMMON_WORDS:
            continue
        if lowered.isdigit() and len(lowered) >= 2:
            tokens.add(lowered)
        elif len(lowered) >= _MIN_TOKEN:
            tokens.add(lowered)
    return tokens


def _grounded_in_reads(sentence: str, evidence: str) -> bool:
    """True when the sentence shares a substantial term with what a tool
    actually returned.

    Deliberately crude, and honest about it: this is word overlap, not meaning.
    It catches the riskiest shape, a cause written in vocabulary no tool
    produced. A sentence blaming "a stale pointer" shares nothing with a log
    that never says stale or pointer, so it is invented. "It hit its 24 GiB memory limit" shares memory
    and 24 with "MemoryError: cannot allocate 24 GiB", so it stays.

    The asymmetry is why crude is acceptable here. A false positive costs one
    symptom-only page, which is the shape the owner asked for anyway. A false
    negative costs a confident wrong diagnosis with a recommended fix attached,
    and acting on that fix can damage a healthy system.
    """
    return _shares_ground(_cause_span(sentence), evidence)


def _shares_ground(claim: str, evidence: str) -> bool:
    """True when `claim` shares a substantial term with what a tool returned.

    The comparison both grounding checks make, held in one place so the causal
    guard and the remedy guard below cannot drift apart about what counts as
    shared. They differ only in the span they hand over.
    """
    if not evidence.strip():
        return False
    wanted = _distinctive_tokens(claim)
    if not wanted:
        return True  # nothing specific asserted; the other guards own this
    return bool(wanted & _distinctive_tokens(evidence))


def _cause_span(sentence: str) -> str:
    """The part of the sentence that states the CAUSE, not the symptom.

    Grounding the whole sentence proved nothing, because the symptom half
    legitimately shares wording with the log. "The deploy failed because the
    local git ref has a stale pointer" and a deploy log both say "failed", so
    the invented half rode in on the true half. The cause is what has to come
    from a reading, so the cause is what gets checked: everything after the
    causal marker.
    """
    match = _CAUSAL_CLAIM_RE.search(sentence)
    if match is None:
        return sentence
    return sentence[match.end():].strip() or sentence


def unbacked_causal_claim(
    answer: str, successful_reads: int, evidence: str = ""
) -> str | None:
    """Nudge if the draft asserts a cause or a number that its reads do not back.

    `successful_reads` counts read-tool calls that returned data this turn, and
    `evidence` is what they returned.

    Returning None the moment `successful_reads > 0` would only ever catch the
    case where the assistant had read NOTHING. A confident wrong diagnosis
    that follows a successful `kubectl_logs` or `loki_query` would go out
    unchecked with its recommended fix attached, and that is most of them.
    Reads greater than zero is true by construction on the path that matters;
    the evidence is in hand and must be used.

    Two gates now. No successful read plus an assertion is unchanged. With
    reads, a causal sentence must share a distinctive term with what the tools
    returned; an attributed or hedged one always passes.
    """
    if _HEDGE_RE.search(answer):
        return None
    if not (_CAUSAL_CLAIM_RE.search(answer) or _QUANTITY_CLAIM_RE.search(answer)):
        return None
    if successful_reads == 0:
        return _zero_read_nudge()
    for sentence in _SENTENCE_SPLIT_RE.split(answer.strip()):
        if not sentence or not _CAUSAL_CLAIM_RE.search(sentence):
            continue
        if _HEDGE_RE.search(sentence) or _ATTRIBUTED_RE.search(sentence):
            continue
        if not _grounded_in_reads(sentence, evidence):
            return (
                "[automatic check, NOT from the person] Your draft names a "
                f"cause: {sentence[:160]!r}. You did run reads this turn, but "
                "nothing they returned uses the terms that sentence does, so it "
                "is a theory rather than a reading. Say the symptom plainly, "
                "and either quote what a tool actually showed you, attribute "
                "the theory explicitly ('the alert itself says ...'), or say it "
                "is unchecked. Do NOT mention this note; reply as if it never "
                "appeared."
            )
    return None


def _zero_read_nudge() -> str:
    return (
        "[automatic check, NOT from the person] Your draft states a cause or a "
        "number, but you ran no successful read this turn, so nothing in front "
        "of you supports it. Either call a read tool and check it, or say "
        "plainly that you have not checked and what you would need to. Do NOT "
        "state it as fact on a guess. Do NOT mention this note; reply as if it "
        "never appeared."
    )


# ── the paging paths ─────────────────────
# The gate above runs only in chat; the assistant's proactive pages need the
# same guard, or they can carry a confident diagnosis with zero checks behind
# it. The no-tools loops (morning line, evening report,
# notify flush) CAN'T call a read tool mid-turn, so their version of honesty
# is different: state the symptom, attribute a relayed cause to the material,
# or say it is unchecked, never diagnose bare. A page may relay what its own
# material states ("the alert itself says the DSN is wrong"): that is
# reporting, not diagnosing, so attributed causes pass.
_ATTRIBUTED_RE = re.compile(
    r"\b(the |that |this |its? )?(alerts?|pings?|monitors?|canary|canaries|"
    r"deadman|logs?|tracebacks?|units?|reports?|messages?|annotations?)\b"
    r"[^.!?]{0,40}\b(says?|said|reports?|reported|shows?|showed|states?|"
    r"stated|calls? it|blames?|blamed|names?|named)\b",
    re.IGNORECASE,
)

# A claim about what a LOG or a FILE contains, which a no-tools pass cannot
# have looked at. Attribution and fabrication read identically in English, and
# `_ATTRIBUTED_RE` above cannot tell them apart: it lists `logs?` and
# `tracebacks?` so a page may relay "the log says the DSN is wrong" when that
# sentence arrived in the ping. In a loop with tools that is fine, because the
# loop may actually have read one.
#
# In a no-tools loop it inverts. A pen flush that says "the scan log shows no
# real findings" when nothing opened the scan log has invented its evidence,
# even when the conclusion happens to be right, which is the worst
# combination: an unchecked guess in the register of a verified one.
# `_ATTRIBUTED_RE` matches "log shows" and would call it honest.
#
# So the no-tools path treats a named artefact as evidence it CANNOT cite; see
# `_UNREAD_EVIDENCE_RE` below.

# The assistant announcing a check: "I'd need to check", "let me look", "ik moet even
# kijken". The subject has to be the assistant, which is why every branch is anchored on
# a first person pronoun or on an imperative addressed to itself.
_ANNOUNCED_CHECK_RE = re.compile(
    r"\b(?:"
    r"i(?:'d| would| will|'ll| am going to)?\s*(?:need to|have to|want to)?\s*"
    r"(?:go and\s+)?(?:check|look|verify|confirm|dig into|look into)\b"
    r"|let me\s+(?:just\s+)?(?:check|look|verify|confirm|see)\b"
    r"|ik\s+(?:moet|zou|ga|wil)\s+(?:even\s+|nog\s+)*"
    r"(?:kijken|checken|nakijken|verifi[eë]ren)\b"
    r"|laat me\s+(?:even\s+)?(?:kijken|checken)\b"
    r"|ik\s+kijk\s+(?:even|er)\b"
    r")",
    re.IGNORECASE,
)

# The false positive that would matter most, so it is excluded by name rather
# than hoped away: "you'd need to check the Grafana board" is advice to the
# reader, and telling somebody where to look is one of the most useful things a
# message can do. Only the assistant's own announced check is the defect.
_CHECK_IS_THE_READERS_RE = re.compile(
    r"\b(?:you|je|jij|u)\b[^.]{0,20}\b(?:need|would|should|moet|zou)\b",
    re.IGNORECASE,
)


# The assistant claiming it acted unprompted. The phrases are short and specific
# because the claim is: everything here is a way of saying "nobody asked me".
_OWN_INITIATIVE_RE = re.compile(
    r"\b(?:"
    r"on my own (?:initiative|account|accord)"
    r"|of my own (?:accord|volition)"
    r"|unprompted"
    r"|nobody asked (?:me|for this)"
    r"|no one asked (?:me|for this)"
    r"|op eigen initiatief"
    r"|uit (?:mezelf|eigen beweging)"
    r"|niemand (?:heeft het |het )?gevraagd"
    r")",
    re.IGNORECASE,
)


def unattributed_relay(message: str, requester: str) -> str | None:
    """Refuse a relayed message that hides, or contradicts, who asked for it.

    THE SHAPE IT CATCHES. A person asks the assistant to sort something out
    with somebody else, and the relayed message opens with "I'm sending this on
    my own initiative". The reader cannot tell who asked for what.

    THE RULE IS WRITTEN IN THREE PLACES, AND THIS IS WHAT CHECKS IT. The tool
    description says the message carries "in it who asked, plainly"; the
    module's own contract line says "ATTRIBUTED + AUDITED. The message carries
    who asked (the requester)"; and the assistant's own manual says
    "always say plainly who asked". The requester is recorded in the audit row
    as `actor`, so the fact is in hand and only the sentence can be wrong.

    IT REFUSES THE CONTRADICTION AND NOT THE OMISSION, which is narrower than
    the bible rule and deliberately so. Claiming own initiative when somebody
    asked is a false statement about why the message exists, and it can be
    detected exactly. Merely not naming the requester is also against the rule,
    but it cannot be checked by looking for the name: that would refuse "the
    call with Alex needs to move", where the name is present and attributes
    nothing, while relays that never name the asker can be fine. A guard that refuses
    correct messages is a guard somebody turns off, so the omission stays a
    prompt rule and only the contradiction is enforced here.

    It also matters beyond the confusion. "On my own initiative" is the framing
    that marks a genuinely autonomous message, the kind quiet hours hold and
    that this system is trying to have less of. A human-driven relay wearing
    that label makes the assistant look more autonomous than it is.

    Returns None when the assistant really is acting unprompted (`requester` is empty
    or "assistant"), which is the case the phrase exists for.
    """
    asked_by = (requester or "").strip()
    if not asked_by or asked_by.lower() == "assistant":
        return None
    draft = (message or "").strip()
    if not draft:
        return None
    if _OWN_INITIATIVE_RE.search(draft):
        return (
            f"you say this is your own initiative, and {asked_by} asked you for "
            f"it. Say who asked, plainly, and send again."
        )
    return None


# Two drafts say the same thing when most of their distinctive terms are the
# same terms. A repeated question scores well above 0.6, a nudge that adds
# something new ("he still needs an answer") around 0.5, and a different ask
# about the same call lower still. 0.6 sits in that gap. A draft holding fewer than three distinctive terms is
# not judged at all: at two terms, one shared word carries the whole fraction.
_SAME_MESSAGE_OVERLAP = 0.6
_MIN_SAMENESS_TERMS = 3


def _clock_of(created_at: object) -> str:
    """The local wall clock of an ISO stamp, or "" when it cannot be read.

    A conversion of a timestamp handed in, not a clock read, so this file stays
    what its failure policy says it is: pure predicates with no I/O.
    """
    try:
        stamp = _dt.datetime.fromisoformat(str(created_at))
    except (TypeError, ValueError):
        return ""
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=_dt.timezone.utc)
    return stamp.astimezone(LOCAL_ZONE).strftime("%H:%M")


def repeated_message(
    message: str, already_sent: list[dict], person: str = "them"
) -> str | None:
    """Refuse a message that puts to somebody a question they were already put.

    THE SHAPE IT CATCHES. The assistant relays a question, gets an answer,
    settles the matter, and then sends the ORIGINAL question again to the same
    person, as if nothing had been answered.

    NOTHING ELSE BETWEEN THE DRAFT AND THE PHONE ASKS WHETHER IT WAS ALREADY
    SENT. The other checks on this seam each read one draft on its own: who
    asked for it, its weekday arithmetic, its language, whether its reader is
    away. A repeated message passes every one of them, because on its own it is
    a perfectly good message. It is only wrong in company: the same question,
    to the same person, minutes after they answered it.

    THE MODEL USUALLY HAS WHAT IT NEEDS AND CAN STILL DO IT, which is why this
    is a check and not a line in the prompt: the thread can show the matter
    settled two turns above the reply the model misreads.

    IT REFUSES SAMENESS AND NOT INTENT. A person can genuinely want a second
    message about one subject, and one that carries something new (an answer, a
    nudge with a reason, a changed time) reads as different enough to pass. A
    false positive costs one rewrite and the refusal says what to write
    instead; a false negative is one duplicate on a phone. Same posture as the
    other guards on this seam.

    `already_sent` is what the assistant has said to this person recently, oldest-first
    as `state.recent_chat_turns` returns it: rows with `text` and, when they
    carry one, `created_at`. Newest is checked first, so the refusal names the
    most recent time the same thing went out.
    """
    draft = _distinctive_tokens(message)
    if len(draft) < _MIN_SAMENESS_TERMS:
        return None
    for row in reversed(already_sent or []):
        earlier = _distinctive_tokens(row.get("text", ""))
        if not earlier:
            continue
        if len(draft & earlier) / len(draft | earlier) < _SAME_MESSAGE_OVERLAP:
            continue
        when = _clock_of(row.get("created_at"))
        sent_at = f" at {when}" if when else ""
        return (
            f"you already sent {person} this{sent_at}, and this draft says the "
            "same thing again. A question asked twice reads as a new question. "
            "Say what is actually new, or tell whoever asked what the answer "
            "already was."
        )
    return None


def announced_check_never_made(answer: str, successful_reads: int) -> str | None:
    """Nudge a draft that says it needs to look, in a turn that never looked.

    THE SHAPE IT CATCHES. A reply such as "for that I'd need to check a few
    things rather than quote numbers from memory", in a turn that made zero
    tool calls. Every word can be true, and the announced check never happens.

    IT IS A DIFFERENT KIND OF WRONG FROM EVERYTHING ELSE IN THIS FILE, and that
    is why it needs its own rule rather than a widened one. Nothing untrue is
    said. No number is invented, no cause asserted, no reader action claimed.
    The reader is simply left holding half a message: "I'd need to check"
    reads as "and I am about to", and on a road that HAS tools it should be. The other guards all ask whether a claim is supported; this one asks
    whether an announced action was taken.

    THE READ COUNT IS THE WHOLE GATE. With a successful read behind it the
    sentence is fine: the loop looked at something, and saying more would be
    needed for the rest is honest. It fires only when the turn read NOTHING,
    which is the case where the announcement stands alone.

    ONLY ON A ROAD THAT CAN LOOK. The morning brief has no tools by
    construction, so there "I would need to check" is a true
    statement about a real limit and `evidence.unchecked_footer` already carries
    it. Wiring this guard into a no-tools loop would nudge it for admitting
    exactly what that contract requires it to admit.

    A nudge, never a strip. The fix is to look, which only the model can do, and
    a sentence removed here would leave an answer that quietly says less rather
    than one that goes and finds out.
    """
    if successful_reads > 0:
        return None
    draft = (answer or "").strip()
    if not draft:
        return None
    if not _ANNOUNCED_CHECK_RE.search(draft):
        return None
    if _CHECK_IS_THE_READERS_RE.search(draft):
        return None
    return (
        "You say you would need to check something, and this turn you read "
        "nothing. You have the read tools: use them now and answer from what "
        "they return. If you are not going to look, say plainly that you have "
        "not checked, rather than leaving it as something still to come. Do "
        "NOT mention this note."
    )


# The ping material itself (alert, monitor, canary, report) stays citable, because
# that really is in front of it.
_UNREAD_EVIDENCE_RE = re.compile(
    r"\b(scan |deploy |build |container |gitleaks |error |the |that )*"
    r"(log|logs|logfile|traceback|stack ?trace|output|console|journal|stderr|stdout)\b"
    # Verbs that describe CONTENTS only. `is`, `are`, `has` and `had` stay
    # out: "the full scan log is on the server" points somebody at a log,
    # which is the single most useful thing a page can do, and gating it would
    # teach the loop to stop naming where to look.
    r"[^.!?]{0,40}\b(shows?|showed|contains?|contained|says?|said|"
    r"reveals?|revealed|lists?|listed)\b",
    re.IGNORECASE,
)


def unbacked_causal_page(text: str) -> str | None:
    """Nudge a page or report that asserts a bare cause it could not check.

    The no-tools variant of `unbacked_causal_claim`: reads are structurally
    zero here, so only CAUSES are gated (the numbers in a page come from the
    pinged material itself) and an attributed or hedged cause passes. Returns
    the nudge to inject, or None when the draft is honest.
    """
    if _UNREAD_EVIDENCE_RE.search(text) and not _HEDGE_RE.search(text):
        # Checked BEFORE the causal gate, and deliberately not excused by
        # attribution: naming a log is what makes this sentence sound checked,
        # so it cannot also be what makes it acceptable.
        return (
            "[automatic check, NOT from the person] Your draft describes what a "
            "log, a traceback or a command's output CONTAINS. This call has no "
            "tools and you opened nothing, so you have not seen any of them; "
            "what you have is the pinged material above and your own memory. "
            "Saying what a log shows is the register of a checked fact, and an "
            "unchecked guess in that register is worse than no message at all. "
            "Rewrite it: say what the ping itself says, name the artefact as "
            "something somebody should READ rather than something you have "
            "read, or leave the claim out. Do NOT mention this note; reply as "
            "if it never appeared."
        )
    if not _CAUSAL_CLAIM_RE.search(text):
        return None
    if _HEDGE_RE.search(text) or _ATTRIBUTED_RE.search(text):
        return None
    return (
        "[automatic check, NOT from the person] Your draft states a CAUSE, but "
        "this call has no tools and you checked nothing, so nothing in front of "
        "you supports a diagnosis beyond what the material above itself states. "
        "Rewrite the message stating the symptom plainly (what failed, when, "
        "what it looked like), and either leave your theory of the cause out, "
        "attribute it explicitly to the material ('the alert itself says ...'), "
        "or say plainly that it is unchecked. Do NOT mention this note; reply "
        "as if it never appeared."
    )


# ── a recommended remedy the run never justified ────────
# Everything above decides whether a CLAIM may leave. A message can also carry
# an instruction: "the local git ref needs clearing on the server before
# deploys will go clean", when nothing is wrong and one transient failure
# heals on the next cycle. A wrong claim costs attention; a wrong remedy, if
# somebody acts on it, costs the state of the machine that runs everything.
#
# So the remedy is gated apart from the claim that motivates it, and on the
# same standard: it may leave only when a distinctive term of the action shares
# ground with something the run actually read. A no-tools loop read nothing, so
# there a state-changing remedy cannot leave at all.
#
# READ-ONLY CHECKS ARE UNTOUCHED, which is why this is a verb list and not a
# test for "an instruction". The page shape this follows: "the server disk is
# almost full, please check df -h / on the server". Naming the one thing to LOOK at is what a page is for; only changing
# state has to be earned. Command SYNTAX is a different seam and stays there:
# `signal_text.names_a_command` drops a sentence handing the reader a shell
# invocation whatever its verb, so this guard reads English rather than shell.
#
# Neither a hedge nor an attribution excuses a remedy, and both excuse a cause.
# "I have not checked, but the git ref needs clearing" is the exact sentence
# this exists for, and a relayed instruction still moves a hand on the box: the
# material a page carries is not a check either, which is why the house rules
# 11 refuses a sender's runbook line outright.
#
# English only, like `_READER_ACTION_RE` and for the same reason: every frame
# below is a grammatical shape rather than a word, and the Dutch shapes are a
# separate list nobody has measured against real Dutch pages yet.

#: Actions that change live state. Read-only verbs are deliberately absent.
_REMEDY_VERBS = (
    "clear", "delete", "rm", "reset", "restart", "reboot", "drop", "purge",
    "kill", "scale", "rotate", "revert", "prune", "requeue",
)
#: The same actions as a gerund and as a past participle, written out rather
#: than derived from the list above: the doubling rules ("dropping",
#: "resetting") are exactly where a generated list goes quietly wrong.
_REMEDY_GERUNDS = (
    "clearing", "deleting", "resetting", "restarting", "rebooting", "dropping",
    "purging", "killing", "scaling", "rotating", "reverting", "pruning",
    "requeuing",
)
_REMEDY_PARTICIPLES = (
    "cleared", "deleted", "reset", "restarted", "rebooted", "dropped",
    "purged", "killed", "scaled", "rotated", "reverted", "pruned",
    "requeued",
)
_REMEDY_BASE_ALT = "|".join(_REMEDY_VERBS)
_REMEDY_ANY_ALT = "|".join(
    _REMEDY_VERBS + _REMEDY_GERUNDS + _REMEDY_PARTICIPLES
)
# Four frames, and each one needs the action to be RECOMMENDED rather than
# reported. A past-tense report ("the signal-cli container restarted at
# 02:10") matches none of them, and it has to stay clean: the change block
# records restarts and the brief is allowed to restate one.
_REMEDY_RE = re.compile(
    # "The local git ref needs clearing", "needs to be cleared", "will need a
    # manual restart".
    rf"\b(?:needs?|needed|will need|requires?|has to be|have to be|must be)\s+"
    rf"(?:to\s+be\s+)?(?:an?|the)?\s*(?:\w+[\s-]+){{0,2}}"
    rf"(?:{_REMEDY_ANY_ALT})\b"
    # "you should restart it", "we need to prune the old images".
    rf"|\b(?:you|we|somebody|someone)\s+(?:should|need to|needs to|"
    rf"will need to|have to|has to|must|could|can|might want to|may want to)"
    rf"\s+(?:\w+[\s-]+){{0,2}}(?:{_REMEDY_BASE_ALT})\b"
    # "I recommend restarting it", "consider a reboot", "the fix is to clear it".
    rf"|\b(?:recommend|suggest|advise|propose|try|consider)\w*\s+"
    rf"(?:\w+[\s-]+){{0,2}}(?:{_REMEDY_ANY_ALT})\b"
    rf"|\b(?:fix|remedy|solution|workaround)\s+(?:is|was|would be)\b"
    rf"[^.!?]{{0,30}}?\b(?:{_REMEDY_ANY_ALT})\b"
    # An imperative: the sentence opens with the action, or "please"/"just"
    # introduces it.
    rf"|(?:^|\bplease\s+|\bjust\s+|\bthen\s+)(?:{_REMEDY_BASE_ALT})\b",
    re.IGNORECASE,
)


def _remedy_span(sentence: str) -> str:
    """The part of the sentence that states the ACTION, not the reasoning.

    `_cause_span` from the other side. The thing an action acts on sits on
    either side of its verb ("the git ref needs clearing", "restart the
    watcher"), so the span is the sentence rather than a tail; what comes off
    is the causal half, which is the claim guard's business and not this one's.
    Without that cut, "you should restart it because the unit is dead" grounds
    on a word the CAUSE happens to share with a log, and the action rides in on
    it.
    """
    match = _CAUSAL_CLAIM_RE.search(sentence)
    if match is None:
        return sentence
    return sentence[: match.start()].strip() or sentence


def _recommends_a_state_change(sentence: str) -> bool:
    """Whether this sentence tells somebody to change the state of a live
    system."""
    return bool(_REMEDY_RE.search(sentence))


def _is_unbacked_remedy(sentence: str, evidence: str) -> bool:
    """Whether this sentence recommends a state change nothing read backs."""
    return _recommends_a_state_change(sentence) and not _shares_ground(
        _remedy_span(sentence), evidence
    )


def unbacked_remedy(text: str, evidence: str = "") -> str | None:
    """Nudge a draft that hands somebody a state-changing repair the run never
    checked, else None.

    `evidence` is what this run's read tools returned. It is empty on a
    no-tools loop, where `_shares_ground` refuses everything, so a page or a
    brief may say what broke and what to look at and may not say what to
    change. A loop that did look keeps a remedy whose action or target the
    readings themselves name, which is the same trade `strip_causal_sentences`
    makes for a diagnosis: looking is what earns the right to say more.
    """
    hits = [
        sentence
        for sentence in _SENTENCE_SPLIT_RE.split((text or "").strip())
        if sentence and _is_unbacked_remedy(sentence, evidence)
    ]
    if not hits:
        return None
    return (
        "[automatic check, NOT from the person] Your draft tells somebody to "
        "change the state of a live system: "
        + " / ".join(one.strip()[:90] for one in hits[:2])
        + ". Nothing you read this run names that action or what it would act "
        "on, so the repair rests on a theory, and it may act on "
        "something that is healthy. Say "
        "what you read and what broke, do not hand the reader a step you or "
        "the system can take, and leave the repair to the person who can "
        "check it first. Do NOT mention this note; reply as if it never "
        "appeared."
    )


def strip_unbacked_remedy(text: str, evidence: str = "") -> str:
    """Drop the sentences handing over an unbacked state-changing repair; keep
    the rest. "" when none survive, which is the caller's signal to fall back
    to its deterministic line."""
    kept = [
        sentence
        for sentence in _SENTENCE_SPLIT_RE.split((text or "").strip())
        if sentence and not _is_unbacked_remedy(sentence, evidence)
    ]
    return " ".join(kept).strip()


# ── a unit nothing read ─────────────────────────────────────────────
# A page can ask the owner to read the log of a unit that exists on no box;
# the reader then guesses more names, all "-- No entries --". A unit is a name a reader
# acts on, so a page may name one only when something it read named it.
# Without the dot a name counts only before "unit", or with two hyphens before
# "service" or "timer": one hyphen is ordinary English ("the health-check
# service answers 502", "a third-party service"), and stripping that sentence
# would take the symptom out of a true page.
_UNIT_NAME_RE = re.compile(
    r"\b([a-z0-9][a-z0-9@_.-]*\.(?:service|timer))\b"
    r"|\b([a-z0-9]+(?:-[a-z0-9]+)+)\s+unit\b"
    r"|\b([a-z0-9]+(?:-[a-z0-9]+){2,})\s+(?:service|timer)\b",
    re.IGNORECASE,
)


def unread_units(text: str, evidence: str) -> list[str]:
    """The systemd-style unit names in `text` that `evidence` never mentions."""
    seen = (evidence or "").lower()
    named = [
        dotted or before_unit or bare
        for dotted, before_unit, bare in _UNIT_NAME_RE.findall(text or "")
    ]
    return [name for name in dict.fromkeys(named) if name.lower() not in seen]


def unread_unit(text: str, evidence: str) -> str | None:
    """Nudge a draft that names a unit nothing read, else None."""
    missing = unread_units(text, evidence)
    if not missing:
        return None
    return (
        "[automatic check, NOT from the person] Your draft names "
        + ", ".join(missing[:3])
        + ", and no tool result or the alert named it, so it may not exist. "
        "Name only a unit you read, or say you could not find which one. Do "
        "NOT mention this note; reply as if it never appeared."
    )


def strip_unread_units(text: str, evidence: str) -> str:
    """Drop the sentences naming a unit nothing read; "" when none survive."""
    kept = [
        sentence
        for sentence in _SENTENCE_SPLIT_RE.split((text or "").strip())
        if sentence and not unread_units(sentence, evidence)
    ]
    return " ".join(kept).strip()


# ── weekday-vs-date consistency ─────────────────────────────────────
# A model can pair a weekday with a date that falls on another day, and the
# reader acts on whichever half they trust. A weekday next to a date is pure
# arithmetic, so it is checked deterministically: the pair must be right for
# some occurrence of that date within ~9 months of today (window, not calendar
# year, so a December chat about early January stays fine while "the same date
# last year fell right" can never excuse today's mistake). English and Dutch
# names, both orders ("24 juli" / "july 24").
_WEEKDAY_NAMES = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4,
    "saturday": 5, "sunday": 6,
    "maandag": 0, "dinsdag": 1, "woensdag": 2, "donderdag": 3, "vrijdag": 4,
    "zaterdag": 5, "zondag": 6,
}
_MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    "januari": 1, "februari": 2, "maart": 3, "mei": 5, "juni": 6, "juli": 7,
    "augustus": 8, "oktober": 10,
}
_ENGLISH_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                     "Saturday", "Sunday")
_WD_ALT = "|".join(_WEEKDAY_NAMES)
_MONTH_ALT = "|".join(_MONTH_NAMES)
_WD_DATE_RE = re.compile(
    rf"\b(?P<wd>{_WD_ALT})\b\s*,?\s*(?:den?\s+)?"
    rf"(?:(?P<day>\d{{1,2}})\s+(?P<month>{_MONTH_ALT})|"
    rf"(?P<month2>{_MONTH_ALT})\s+(?P<day2>\d{{1,2}}))\b",
    re.IGNORECASE,
)


# A sentence saying the systems are fine, which must not go out while a
# paged alert still fires: "nothing broke overnight", "everything up",
# "all systems green". Only system-status wording: a bare "all good" or
# "alles in orde" is everyday speech ("all good, I'll book it") and would block
# an unrelated message for as long as any page fires. English and Dutch,
# because a message goes out in its reader's language.
_ALL_CLEAR_RE = re.compile(
    r"\b(nothing\s+(?:new\s+)?(?:is\s+|has\s+)?(?:broke|broken|down|failing)"
    r"|everything(?:'s|\s+is)?\s+(?:up|green|running)"
    r"|all\s+systems\s+\w+"
    r"|niets\s+(?:is\s+)?(?:kapot|stuk|down)"
    r"|alle\s+systemen\s+\w+)\b",
    re.IGNORECASE,
)


def all_clear_while_firing(text: str, firing_names) -> str | None:
    """A plain sentence when `text` says nothing is wrong while alerts in
    `firing_names` still fire, or None. Pure: the caller reads the alerts."""
    if not firing_names:
        return None
    match = _ALL_CLEAR_RE.search(text)
    if not match:
        return None
    return (
        f"the draft says {match.group(0)!r}, but these alerts paged and are "
        f"still firing: {', '.join(firing_names)}"
    )


def weekday_mismatch(text: str, today) -> str | None:
    """A plain sentence describing the first weekday/date pair in `text` that
    is wrong in every nearby year, or None when all pairs check out.

    `today` is a `datetime.date`; a candidate occurrence of the date counts
    only within ~9 months of today (either side), so "friday 2 january" stays
    fine in late December while a year-away occurrence can never excuse the
    pair. Pure: no clock reads, no I/O.
    """
    for match in _WD_DATE_RE.finditer(text):
        claimed = _WEEKDAY_NAMES[match.group("wd").lower()]
        day = int(match.group("day") or match.group("day2"))
        month = _MONTH_NAMES[(match.group("month") or match.group("month2")).lower()]
        dates = []
        for year in (today.year - 1, today.year, today.year + 1):
            try:
                date = _dt.date(year, month, day)
            except ValueError:
                continue
            if abs((date - today).days) <= 270:
                dates.append(date)
        if not dates or any(date.weekday() == claimed for date in dates):
            continue
        nearest = min(dates, key=lambda date: abs((date - today).days))
        return (
            f"the draft says {match.group(0)!r}, but {nearest.day} "
            f"{nearest.strftime('%B')} {nearest.year} is a "
            f"{_ENGLISH_WEEKDAYS[nearest.weekday()]}"
        )
    return None


def wrong_weekday(answer: str, today) -> str | None:
    """Nudge when the draft pairs a weekday with a date that never falls on
    it (see `weekday_mismatch`), else None."""
    mismatch = weekday_mismatch(answer, today)
    if mismatch is None:
        return None
    return (
        f"[automatic check, NOT from the person] {mismatch}. Weekdays are "
        "arithmetic, never memory: fix the weekday or the date (agenda_view "
        "shows the calendar if you need it), then answer again. Do NOT "
        "mention this note; reply as if it never appeared."
    )


# ── board-state statements ──────────────────────────────────────────
# The write guard asks "did you DO this?", the causal guard "did you LOOK?".
# This one narrows the LOOK question to the board: "nothing on the board is
# yours", said without reading the board, is a guess dressed as a fact. A
# statement about what is (or is not) on the board or someone's task list must
# be backed by a successful GitHub read this turn; a calendar read does not
# count, which is why the generic causal gate cannot catch it.
_BOARD_STATE_RE = re.compile(
    r"\b(geen (open(staande)?\s+)?(issues?|taken|items|punten)|"
    r"maar (één|een|\d+) (concrete\s+)?(taak|taken|issues?)|"
    r"niets (open|toegewezen)|(board|backlog) (is |staat )?(leeg|schoon)|"
    r"no (open |unassigned )?(issues?|tasks?|items)|"
    r"nothing (open|assigned|waiting|on the board)|"
    r"(board|backlog) (is )?(empty|clean|clear)|"
    r"only (one|\d+) (open )?(tasks?|issues?|items?)|"
    r"\d+ open (issues?|tasks?|items|taken)|"
    r"(all|everything|alles) (is )?(closed|done|dicht|gesloten|afgerond))\b",
    re.IGNORECASE,
)


def unbacked_board_statement(answer: str, board_reads: int) -> str | None:
    """Nudge when the draft states board/task-list state with no successful
    GitHub read (or board write) behind it this turn, else None.

    `board_reads` counts gh_* reads that returned data plus successful
    `github_act` calls. Hedged drafts pass: saying you have not checked is
    the honest move this guard exists to encourage.
    """
    if board_reads > 0:
        return None
    if _HEDGE_RE.search(answer):
        return None
    if not _BOARD_STATE_RE.search(answer):
        return None
    return (
        "[automatic check, NOT from the person] Your draft states what is, or "
        "is not, on the board or someone's task list, but you ran no "
        "successful GitHub read this turn, so nothing in front of you "
        "supports it. Check first (gh_issue_list, gh_issue_view), or say "
        "plainly that you have not checked the board. Do NOT mention this "
        "note; reply as if it never appeared."
    )


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def strip_causal_sentences(text: str, evidence: str = "") -> str:
    """Symptom-only last resort: drop every sentence that asserts a
    bare, unattributed, unhedged cause; keep the rest.

    Used when a nudged page STILL names an unchecked cause. The page must go
    out, a gate that blocks a page is worse than the claim it blocks, just
    without the diagnosis. Returns "" when nothing survives; the caller falls
    back to its raw symptom line.

    With `evidence`, a cause that a tool result actually backs is KEPT. That is
    the whole point of having looked: a diagnosis drawn from a log line is worth
    reading, and stripping it would train the loop to say less rather than to
    check more. Without evidence the behaviour is unchanged, which is what the
    no-tools callers want.
    """
    kept = []
    for sentence in _SENTENCE_SPLIT_RE.split(text.strip()):
        if not sentence:
            continue
        if (
            _CAUSAL_CLAIM_RE.search(sentence)
            and not _HEDGE_RE.search(sentence)
            and not _ATTRIBUTED_RE.search(sentence)
            and not _grounded_in_reads(sentence, evidence)
        ):
            continue
        kept.append(sentence)
    return " ".join(kept).strip()


# Issue references look like "#42", or are spelled out: "issue 42", "PRD
# 17", "ticket #12". Two digits minimum: "#1" is far more often a heading or an
# ordinal than an issue. The spelled-out form counts too, so a page cannot
# blame a fault on "issue 42" without a read that returned it.
_ISSUE_REF_RE = re.compile(r"(?:#|\b(?:issue|PRD|ticket)\s+#?)(\d{2,5})\b", re.IGNORECASE)


def fabricated_issue_numbers(
    answer: str,
    seen_numbers: set[int],
    context_texts: tuple[str, ...] = (),
) -> str | None:
    """Nudge when the draft cites issue numbers no tool actually returned.

    The sibling guard `unbacked_board_statement` asks whether the assistant read the
    board at all. That is not enough. A model can run real reads and then
    present a list of issues with titles, labels, assignees and timestamps
    that do not exist. Every read succeeded, so the read-count guard passes and
    the fabrication reaches a person as though it were a board dump.

    Counting reads proves the assistant looked. It cannot prove that what it wrote is
    what it saw. This compares the numbers in the draft against the numbers the
    tools actually returned, which is the part that can be invented.

    Numbers the person themselves raised are backed: answering "what about
    an issue" by naming an issue is not a fabrication, it is the topic.
    """
    invented = unread_issue_numbers(answer, seen_numbers, context_texts)
    if not invented:
        return None
    shown = ", ".join(f"#{number}" for number in invented[:8])
    more = "" if len(invented) <= 8 else f" (and {len(invented) - 8} more)"
    return (
        "[automatic check, NOT from the person] Your draft cites "
        f"{shown}{more}, and no tool result this turn contains those numbers. "
        "Do not describe issues you have not fetched: numbers, titles, labels "
        "and dates that look right but were not read are worse than saying "
        "nothing, because they cannot be told apart from real ones. Fetch them "
        "(gh_issue_list, gh_issue_view) and use what comes back, or drop them "
        "and say what you actually checked. Do NOT mention this note; reply as "
        "if it never appeared."
    )


def unread_issue_numbers(
    answer: str,
    seen_numbers: set[int],
    context_texts: tuple[str, ...] = (),
) -> list[int]:
    """The issue numbers `answer` cites that no reading and no context holds.

    The comparison behind `fabricated_issue_numbers`, on its own so a seam
    that refuses rather than nudges (`message_teammate`) can word its
    own answer. Sorted, so a refusal names them in a stable order.
    """
    cited = {int(number) for number in _ISSUE_REF_RE.findall(answer)}
    if not cited:
        return []
    mentioned: set[int] = set()
    for text in context_texts:
        mentioned.update(int(number) for number in _ISSUE_REF_RE.findall(text))
    return sorted(cited - seen_numbers - mentioned)


def strip_unread_issue_sentences(answer: str, seen_numbers: set[int]) -> str:
    """Drop the sentences citing an issue number no reading holds; "" when
    none survive."""
    kept = [
        sentence
        for sentence in _SENTENCE_SPLIT_RE.split((answer or "").strip())
        if sentence and not unread_issue_numbers(sentence, seen_numbers)
    ]
    return " ".join(kept).strip()


# A commit sha as a CITATION: hex, seven to forty wide, with at least one letter
# AND one digit, and not a piece of a dashed token. Stricter than `_SHA_RE`,
# which only has to recognise bookkeeping: a refusal built on that one would
# read a phone number ("5550100123") or a UUID segment as a sha nobody read.
_CITED_SHA_RE = re.compile(
    r"(?<![-\w])(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{7,40}(?![-\w])",
    re.IGNORECASE,
)
# Every free-standing number a reading holds, the way the door counts them.
_READ_NUMBER_RE = re.compile(r"(?<!\d)\d{2,6}(?!\d)")


def cited_shas(text: str) -> list[str]:
    """Every commit sha `text` holds, lower-cased, in order, each once."""
    return list(dict.fromkeys(found.lower() for found in _CITED_SHA_RE.findall(text or "")))


def unread_shas(text: str, evidence_texts: tuple[str, ...]) -> list[str]:
    """The commit shas `text` cites that no evidence text holds, in order.

    A cited sha is backed when it and a sha in the evidence are one the prefix
    of the other, so "fedcba98" is backed by a full forty-wide sha. A sha the
    model remembers rather than reads (a journal line saying "Deploy at
    9abc1234" when deploy_status said fedcba98) is the case this catches.
    """
    read = {sha for evidence in evidence_texts for sha in cited_shas(evidence)}
    return [
        sha
        for sha in cited_shas(text)
        if not any(sha.startswith(seen) or seen.startswith(sha) for seen in read)
    ]


def unread_citations(
    text: str,
    evidence_texts: tuple[str, ...],
    context_texts: tuple[str, ...] = (),
) -> list[str]:
    """The issue numbers and shas `text` cites that no evidence text holds.

    What a memory write is checked against before it is stored: a note
    is read back into every later run as fact, so a number in it has to have
    come from a tool. `context_texts` are what the writer already holds as
    given (the worklist titles), whose issue numbers need no fresh read.
    """
    seen = {
        int(found)
        for evidence in evidence_texts
        for found in _READ_NUMBER_RE.findall(evidence)
    }
    issues = unread_issue_numbers(text, seen, context_texts)
    return [f"#{number}" for number in issues] + unread_shas(text, evidence_texts)


# A clause in the assistant's own note saying it already told a teammate ("Already
# briefed the owner this morning; not repeating"). The brief wrote those before it
# sent, and in runs that left the item out, and every later loop read them back
# as fact, so an item can go unsaid for days on their strength.
# Only a telling to a TEAMMATE counts, so "reported to the provider's support as
# ticket 12345" is a finding and stays.
_TOLD_VERBS = r"(?:briefed|told|flagged|reported|raised|communicated|notified)"
_CLAUSE_END_RE = re.compile(r"(?<=[.;!?,])\s+")


def _told_claim_re(teammates: Sequence[str]) -> re.Pattern[str]:
    """A telling to one of `teammates`, him, her, them or the team, or the
    bare "already briefed" and "not repeating" forms."""
    named = [re.escape(name) for name in teammates if name]
    who = "|".join([*named, "him", "her", "them", "the team"])
    return re.compile(
        rf"\balready\s+{_TOLD_VERBS}\b(?!\s+to\s+(?!(?:{who})\b))"
        rf"|\b{_TOLD_VERBS}\s+(?:to\s+)?(?:{who})\b"
        r"|\bnot\s+(?:repeating|re-?rais(?:ed|ing))\b",
        re.IGNORECASE,
    )


def without_told_claims(text: str, teammates: Sequence[str]) -> str:
    """`text` with every clause claiming the assistant told a teammate taken out.

    Clauses split on sentence ends and commas, so a deadline sharing a
    sentence with the claim is kept. Whether someone was told is the ledger's
    to say (`reported_items.tellings`), never a note's.
    """
    pattern = _told_claim_re(teammates)
    kept = [
        clause
        for clause in _CLAUSE_END_RE.split((text or "").strip())
        if not pattern.search(clause)
    ]
    return " ".join(kept).strip().rstrip(",;").strip()


# The assistant narrating its own next step, the scratchpad rather than the
# message, such as a reply opening with "Let me check the current state of
# this service". Anchored on
# a sentence start and on the assistant's own reading verbs, so "let me know", "let me
# check with a teammate" and "you could check the board" are not it.
_NARRATION_RE = re.compile(
    r"(?:^|[.!?]\s+)(?:(?:ok(?:ay)?|now|first|right),?\s+)?"
    r"(?:let me\s+(?:just\s+|first\s+|quickly\s+)?"
    r"(?:check|look|re-?read|re-?check|verify|pull|fetch|query|dig|search|grab)\b"
    r"(?!\s+(?:with|in with)\b)"
    r"|laat me\s+(?:even\s+)?(?:kijken|checken|nakijken|nalezen)\b)",
    re.IGNORECASE,
)

# A tool result pasted into a message. A field label in snake_case
# ("change_feed: ...") is a key out of a tool's own answer and
# never a word a person writes; tool-call markup is the model typing a call
# instead of making one.
_TOOL_FIELD_RE = re.compile(r"(?:^|\s)[a-z]+_[a-z0-9_]+:\s", re.MULTILINE)
_TOOL_MARKUP_RE = re.compile(
    r"</?(?:function_calls|invoke|parameter|tool_use|tool_result|thinking)\b",
    re.IGNORECASE,
)


def narrated_monologue(message: str) -> bool:
    """True when the message narrates the assistant's own next step ("Let me check")."""
    return bool(_NARRATION_RE.search(message or ""))


def pasted_tool_output(message: str) -> bool:
    """True when the message carries tool-call markup or a tool's field labels."""
    text = message or ""
    return bool(_TOOL_MARKUP_RE.search(text) or _TOOL_FIELD_RE.search(text))


def issue_numbers_in(text: str) -> set[int]:
    """Every issue number a tool result mentions, for the guard above."""
    return {int(number) for number in _ISSUE_REF_RE.findall(text)}


# ── liveness against the grounded blocks ────────────────────────────
# The read-counter guards above ask "did you look?". On a no-tools loop the
# answer is structurally "no", so they cannot help: a brief can assert a dead
# deploy pipeline, expired tokens and freshly rotated secrets, none of which it
# has read. `fabricated_issue_numbers` is
# the one guard that already works on this surface, because it compares what
# the draft says against what the tools returned. This does the same for
# system state: the draft may only restate what the grounded blocks carry.
#
# WHAT THIS IS. `subjects` is `evidence.subjects()`: lowercase subject name ->
# Fact, `.state` in {"ok", "empty", "unknown"} plus a rendered `.value`.
# `grounded_blocks` is the rest of what was assembled before the call (the
# change feed, the carried items, the support inbox). A sentence is IN SCOPE
# when it names a bundle subject, and also when it puts something in trouble
# or claims an event without naming one. In scope, the check is
# claim-to-evidence: every state word the sentence uses has to be a word the
# subject's own reading uses, or one on the same axis; every event it claims
# has to be an event the reading records; every date and number has to be one
# of the blocks' own. Absent evidence is never good news, so a general all-clear
# ("all good", "on track", "nothing to worry about", "all five are green") is
# unsupported by construction: no reading of some subjects can back a claim
# about everything.
#
# WHERE THE EVIDENCE FOR A SENTENCE LIVES. A trouble-or-fine claim about a
# subject the bundle really read is answered by that subject's fact alone;
# nothing else may license it, which is why a stamp lifted from the change
# feed cannot rescue "the pipeline is dead". Everything else is answered by
# the other grounded blocks and survives as a restatement (every date and
# number in it present in those blocks): a sentence naming no bundle subject,
# a sentence about `change_feed`, whose fact is only the feed's marker and
# carries no news, and an event claim ("restarted", "landed") that no fact
# records. With no blocks passed in there is nothing to check a restatement
# against, so one carrying a concrete stamp is left alone rather than deleted;
# a claim about a subject the bundle read never gets that benefit.
#
# WHERE IT IS STILL PHRASING, AND A READER SHOULD NOT TRUST IT FURTHER. Scope
# is no longer decided by a list of assertion phrasings, so a rephrasing
# nobody predicted still lands in the check as long as it names a subject.
# Three parts stay vocabulary, and each is a real hole:
#   - a sentence naming NO subject is only recognised through the word lists
#     below: a new problem or an event needs a restatement to survive, but a
#     bare reassurance ("all quiet") is left alone unless it reads as a
#     general all-clear, because the calm one-line brief the house rules bless
#     names no subject either. What stops a general all-clear from being the
#     cheapest brief is the coverage block (`evidence.render_coverage`), which
#     names what was never read; this guard only catches the phrasings below;
#   - matching a claim against a reading compares words and axes, not
#     meaning, so a claim whose wording shares no axis with the reading is
#     dropped even when a person would call it a fair summary, and a reading
#     that names one trouble on an axis licenses another word on that same
#     axis;
#   - a blanket word sitting on several axes ("fine", "ok", "green",
#     "healthy") has to be cleared on every axis it touches, because it claims
#     every one of them.
# `state` describes the READ, not health: "ok" means the read succeeded, so a
# real failure lives in `.value`, not in the state. That is why a negative
# claim is checked against the value text and never against the state alone.




class Fact(Protocol):
    """The shape this guard needs from an evidence-bundle fact.

    Structural, so `claims` keeps no import of `evidence` (the bundle is
    assembled by the caller and passed in)."""

    state: str
    value: str


# Aliases a person-facing sentence uses for each bundle subject. Naming one of
# these is what puts a sentence in scope, so the list is the guard's reach:
# a subject nobody wired an alias for is checked only through the word lists.
_SUBJECT_ALIASES: dict[str, tuple[str, ...]] = {
    "deploy": ("deploy", "deployment", "pipeline", "auto-deploy", "autodeploy", "timer"),
    "components": ("stack", "component", "pod", "service"),
    "alerts": ("alert", "page"),
    "change_feed": ("commit", "issue", "main", "change feed", "change record"),
    "secrets": ("secret", "rotation", "token", "pat", "credential"),
}
_ALIAS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (subject, re.compile(r"\b(?:%s)s?\b" % "|".join(re.escape(alias) for alias in aliases),
                         re.IGNORECASE))
    for subject, aliases in _SUBJECT_ALIASES.items()
)


def _word_pattern(*alternatives: str) -> re.Pattern[str]:
    """One word list as a whole-word pattern."""
    return re.compile(r"\b(?:%s)\b" % "|".join(alternatives), re.IGNORECASE)


@dataclass(frozen=True)
class _Axis:
    """One axis a reading can speak on, in both directions."""

    trouble: re.Pattern[str]
    fine: re.Pattern[str]


# Three axes, because a clearance only counts on the axis the reading itself
# cleared: "nothing overdue" is an age reading, so it backs "nothing overdue"
# and it does not back "rotation is healthy". "silent" is deliberately absent
# from `reachable`: the alerts fact renders triage decisions ("-> silent"), so
# the word carries no health here.
_AXES: dict[str, _Axis] = {
    "reachable": _Axis(
        trouble=_word_pattern(
            "dead", "down", "dark", "offline", "stopped", "stopping",
            "unreachable", "stuck", "hung", "gone", "degraded", "missing",
        ),
        fine=_word_pattern(
            "up", "alive", "live", "running", "online", "active", "healthy",
            "green", "ok", "okay", "fine", "quiet", "calm", "stable", "normal",
        ),
    ),
    "working": _Axis(
        trouble=_word_pattern(
            "broken", "failed", "failing", "fails", "fail", "failure",
            "failures", "error", "errors", "erroring", "crash", "crashed",
            "crashing", "red", "threw", "throwing", "blocked", "timeout",
            "timed out", "timing out", r"[45]\d{2}s?",
        ),
        fine=_word_pattern(
            "succeeded", "success", "successful", "passed", "passing", "clean",
            "cleanly", "recovered", "fixed", "working", "healthy", "green",
            "ok", "okay", "fine",
        ),
    ),
    "current": _Axis(
        trouble=_word_pattern(
            "overdue", "stale", "expired", "expiring", "lapsed", "late",
            "behind", "pending", "out of date", r"\d+ days? old",
        ),
        fine=_word_pattern(
            "fresh", "current", "renewed", "valid", "recent", "up to date",
            "in date",
        ),
    ),
}

# Kept under its old name because `_is_green_telemetry` reads it: a number
# sitting next to trouble is the news, not a green readout.
_NEGATIVE_STATE_RE = re.compile(
    "|".join(axis.trouble.pattern for axis in _AXES.values()), re.IGNORECASE
)



# Claims that a specific thing HAPPENED. No axis clears these: the reading
# either records the event in its own words or it does not, which is what
# separates "nothing overdue" (an age reading) from "everything rotated" (an
# event nothing in the bundle records).
_EVENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\brotat(?:e|es|ed|ing|ion|ions)\b", re.IGNORECASE),
    re.compile(r"\bland(?:s|ed|ing)\b", re.IGNORECASE),
    re.compile(r"\brestart(?:s|ed|ing)\b", re.IGNORECASE),
    re.compile(r"\bmerg(?:e|es|ed|ing)\b", re.IGNORECASE),
    re.compile(r"\bclos(?:e|es|ed|ing)\b", re.IGNORECASE),
)




_DATE_TOKEN_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
# Hours and minutes only: a brief may shorten a rendered 14:16:56 to 14:16, so
# the seconds must not become a token of their own that no block contains.
_CLOCK_TOKEN_RE = re.compile(r"(?<!\d)\d{1,2}:\d{2}")
_NUMBER_TOKEN_RE = re.compile(r"\b\d{2,}\b")




def _tokens_in(sentence: str) -> list[str]:
    """Every date, clock time and two-or-more-digit number in the sentence.

    A timestamp is taken as its date and its hh:mm, never as the loose digits
    inside it: "2026-08-14T02:10:00Z" is a date plus a time, so a block that
    renders the same moment with seconds still backs it."""
    dates = _DATE_TOKEN_RE.findall(sentence)
    remainder = _DATE_TOKEN_RE.sub(" ", sentence)
    times = _CLOCK_TOKEN_RE.findall(remainder)
    remainder = _CLOCK_TOKEN_RE.sub(" ", remainder)
    return dates + times + _NUMBER_TOKEN_RE.findall(remainder)


def _restates_grounded(sentence: str, grounded: str) -> bool:
    """True when the sentence is a restatement of the other grounded blocks:
    it carries at least one date or number, and every one of them is in those
    blocks.

    With no blocks passed in there is nothing to check against, so a sentence
    carrying a concrete stamp is given the benefit of the doubt: the block
    that would back it was never handed to the guard. A sentence with no stamp
    at all is never a restatement, which is why "the commit landed cleanly"
    stays flagged either way."""
    tokens = _tokens_in(sentence)
    if not tokens:
        return False
    if not grounded.strip():
        return True
    return all(token in grounded for token in tokens)




# ── openclaw's own plumbing ────────────────────────
# The brief is a summary of the day for a person. A deploy sha, a routing
# decision, how many components were counted, how fresh the secret exporter is:
# all true, all deterministic, and all about how openclaw works rather than
# about anything the reader does. A brief grounded in the record, which is
# written in this vocabulary, comes out faithful and unreadable, opening with
# lines like "Deploy is at 4d4d4d4d since <timestamp>". Nobody reads those,
# which costs exactly as much as lying does.
#
# Prompted for as well, and guarded here because the prompt is not allowed to
# be the only thing holding a load-bearing rule.

# A commit sha: hex, at least seven wide, and carrying a digit. The digit is
# what keeps ordinary words out ("defaced" is seven hex letters).
_SHA_RE = re.compile(r"\b(?=[0-9a-f]{7,40}\b)[0-9a-f]*\d[0-9a-f]*\b", re.IGNORECASE)
# How openclaw routed something, in openclaw's own words.
_ROUTING_RE = re.compile(
    r"\b(batch-page|batch-noise|page-raw|dead[- ]?letter|routed to|"
    r"suppressed|deduped)\b",
    re.IGNORECASE,
)
# The bookkeeping behind a reading, rather than the reading.
_BOOKKEEPING_RE = re.compile(
    r"\b(exporter|secret registry|tracked secrets?|audit rows?|"
    r"\d+\s+tracked|\d+\s+components?\s+checked|report marker|"
    r"change feed|evidence bundle)\b",
    re.IGNORECASE,
)


def _is_own_plumbing(sentence: str) -> bool:
    """True when the sentence reports how openclaw works rather than something
    the reader acts on.

    No trouble-word escape hatch, unlike green telemetry, and the difference is
    the point. A green ratio next to something down IS the news, so that guard
    steps aside; plumbing next to something down is still plumbing. Plumbing
    lines tend to carry a trouble word ("two commits pending", "the exporter
    is stale"), so an escape hatch here would let them through.

    The paragraph above is about the brief, which does not report breakage at
    all: something
    broken is a page at the moment it breaks. `patrol` and `triage` apply it now
    as well, and the reason for no escape hatch does not carry over unexamined
    on either road: patrol may go quiet, so a strip there costs nothing, while
    the triage road pages and `triage._plumbing_gate` refuses the strip when
    what survives no longer names the alert. A third caller must make that same
    argument for itself rather than inherit this one.
    """
    return bool(
        _SHA_RE.search(sentence)
        or _ROUTING_RE.search(sentence)
        or _BOOKKEEPING_RE.search(sentence)
    )


def own_plumbing(draft: str) -> str | None:
    """Nudge when the draft reports openclaw's own bookkeeping, else None."""
    flagged = [
        sentence
        for sentence in _SENTENCE_SPLIT_RE.split(draft.strip())
        if sentence and _is_own_plumbing(sentence)
    ]
    if not flagged:
        return None
    return (
        "[automatic check, NOT from the person] Your draft reports your own "
        f"plumbing: {flagged[0][:160]!r}. A deploy sha, how you routed an "
        "alert, how many components you counted, how fresh an exporter is: all "
        "true, and none of it is anything the reader does something about. Say "
        "what happened and what it was about, in their words. Do NOT mention "
        "this note; reply as if it never appeared."
    )


def strip_own_plumbing(draft: str) -> str:
    """Drop the plumbing sentences; keep the rest. "" when nothing survives."""
    kept = [
        sentence
        for sentence in _SENTENCE_SPLIT_RE.split(draft.strip())
        if sentence and not _is_own_plumbing(sentence)
    ]
    return " ".join(kept).strip()


# ── green telemetry ─────────────────────────────────────────────────
# "11/11 components up, disk 41%, cert good for 62 days" is true, deterministic
# and worthless: it fills the brief with numbers nobody acts on, and it trains
# the reader to skim. Report the numbers only when they are the problem.
_RATIO_RE = re.compile(r"\b(\d{1,3})\s*(?:/|\s+of\s+|\s+out of\s+)\s*(\d{1,3})\b", re.IGNORECASE)
# The trailing word boundary belongs to the spelled-out branches only. Behind
# "%" it can never match unless a word character follows, so "disk 41%." and
# "41% today." would slip through and only "41 percent" would be caught.
_PERCENT_RE = re.compile(r"\b(\d{1,3})\s*(?:%|percent\b|procent\b)", re.IGNORECASE)
_DISK_WORD_RE = re.compile(r"\b(disk|storage|volume|filesystem|schijf)\b", re.IGNORECASE)
_CERT_WORD_RE = re.compile(r"\b(cert|certs|certificate|certificates|tls|ssl)\b", re.IGNORECASE)
_DAYS_LEFT_RE = re.compile(r"\b(\d{1,4})\s*(?:days?|dagen)\b", re.IGNORECASE)
_ALL_UP_RE = re.compile(
    r"\ball\s+\d{1,3}\s+\w+\s+(are\s+)?(up|green|healthy|ok|fine)\b", re.IGNORECASE
)
# Where a number stops being green. A disk under 80% and a certificate with
# three weeks left are readouts; past those they are the news.
_DISK_ALARM_PERCENT = 80
_CERT_ALARM_DAYS = 21


def _is_green_telemetry(sentence: str) -> bool:
    """True when the sentence is a healthy-number readout: a full ratio, an
    unremarkable disk percentage, a far-off certificate expiry, an "all N up"
    count. A number that has crossed into trouble is not green, and neither is
    one sitting next to something that is down."""
    if _NEGATIVE_STATE_RE.search(sentence):
        return False  # a number attached to a problem is the point of the brief
    if _ALL_UP_RE.search(sentence):
        return True
    ratio = _RATIO_RE.search(sentence)
    if ratio is not None and ratio.group(1) == ratio.group(2):
        return True
    percent = _PERCENT_RE.search(sentence)
    if (
        percent is not None
        and _DISK_WORD_RE.search(sentence)
        and int(percent.group(1)) < _DISK_ALARM_PERCENT
    ):
        return True
    days = _DAYS_LEFT_RE.search(sentence)
    return bool(
        days is not None
        and _CERT_WORD_RE.search(sentence)
        and int(days.group(1)) >= _CERT_ALARM_DAYS
    )


def green_telemetry(draft: str) -> str | None:
    """Nudge when the draft reports healthy numbers nobody asked for, else
    None. Component ratios, disk percentages, cert countdowns and "all N up"
    counts belong in the brief only when they are the problem."""
    flagged = [
        sentence
        for sentence in _SENTENCE_SPLIT_RE.split(draft.strip())
        if sentence and _is_green_telemetry(sentence)
    ]
    if not flagged:
        return None
    return (
        "[automatic check, NOT from the person] Your draft reports healthy "
        f"numbers: {flagged[0][:160]!r}. Component counts, disk percentages "
        "and certificate countdowns go in the brief only when they are the "
        "problem; a green reading is not news and it buries the part that is. "
        "Drop the readout and keep what the person has to act on. Do NOT "
        "mention this note; reply as if it never appeared."
    )


def strip_green_telemetry(draft: str) -> str:
    """Drop the healthy-number sentences; keep the rest. "" when nothing
    survives."""
    kept = [
        sentence
        for sentence in _SENTENCE_SPLIT_RE.split(draft.strip())
        if sentence and not _is_green_telemetry(sentence)
    ]
    return " ".join(kept).strip()


# ── language ────────────────────────────────────────────────────────
# A model-written draft can arrive in a language its reader does not read. The
# person's language is a field on their profile, so the mismatch is checkable.
# Word lists are deliberately DISJOINT: a word that exists in both languages
# ("is", "in", "of", "we", "was") carries no signal and is left out.
_DUTCH_STOPWORDS = frozenset(
    "de het een en niet dat zijn voor met naar ik nog wel maar ook geen aan om "
    "te wordt heeft hebben moet kan deze die jij jullie gaat staat even gewoon "
    "zo dus weer iets niks hoe waarom want als dan uit".split()
)
_ENGLISH_STOPWORDS = frozenset(
    "the and not that are for with to i you your there still but also no at it "
    "has have been they what when all one out about into just more than then "
    "now only some any can did does up down first".split()
)
_WORD_RE = re.compile(r"[a-zA-Z']+")


def wrong_language(draft: str, expected_lang: str | None) -> str | None:
    """Nudge when the draft is plainly not in `expected_lang` ("nl" or "en"),
    else None. `expected_lang` None means the caller has no opinion.

    A cheap detector, not a classifier: it counts stopwords from two small
    disjoint lists and only fires when the other language leads clearly. A
    false positive costs exactly one re-prompt, which is why this returns a
    nudge and why it must NEVER be used to drop or block a message.
    """
    if expected_lang not in ("nl", "en"):
        return None
    words = [word.lower() for word in _WORD_RE.findall(draft)]
    dutch = sum(1 for word in words if word in _DUTCH_STOPWORDS)
    english = sum(1 for word in words if word in _ENGLISH_STOPWORDS)
    wanted, other = (dutch, english) if expected_lang == "nl" else (english, dutch)
    if other < 3 or other <= wanted:
        return None
    language = "Dutch" if expected_lang == "nl" else "English"
    return (
        "[automatic check, NOT from the person] This person reads "
        f"{language}, and your draft is not in {language}. Write the whole "
        f"message in {language}, including any quoted status line. Do NOT "
        "mention this note; reply as if it never appeared."
    )


# ── command syntax (the voice half) ───────────────────────
# `core.voice` says it in so many words: never write command syntax into a
# message, run the safe read-only ones yourself and then tell the person what
# you found. Prose plus a line-anchored strip in `signal_text` is not enough
# on its own: a model told so still hands the reader commands.
#
# This is presentation, not grounding. It never asks whether the loop checked
# anything, only that it says what it found instead of what to type, so it is
# safe on a loop that HAS tools and in fact belongs there:
# a loop with tools is the one that can go and run the read itself. The strip
# in `signal_text.strip_markdown` still stands behind it; this is the nudge
# that gets asked first, so the strip rarely has to cut a sentence.


def command_syntax(draft: str) -> str | None:
    """Nudge when the draft hands the reader a command to run, else None."""
    if not _signal_text.names_a_command(draft):
        return None
    # "in words rather than repeating the command" is load-bearing, not
    # politeness. The strip runs after this nudge, so a compliant answer that
    # quotes the command back ("I ran systemctl status
    # harness-webhook.service and it is active") would be cut and the
    # reply would go out empty. `signal_text._names_an_invocation` keeps the
    # version without the operand; this keeps the model on that version.
    return (
        "[automatic check, NOT from the person] Your draft hands the reader a "
        "command to run. You have the read-only tools: run that check "
        "yourself and write one plain sentence saying what came out, naming "
        "the thing in words rather than repeating the command ('the dispatcher "
        "has been active since 09:02', not the systemctl line). If you cannot "
        "run it, say plainly what you cannot see. Do NOT mention this note; "
        "reply as if it never appeared."
    )


# ── the two things no read can back (patrol) ─────────────────────────
#
# Patrol's causal guard is all-or-nothing on reads: it strips a bare cause only
# when the pass read NOTHING. Having read something therefore licensed saying
# anything, including lines with claims no amount of reading can back.
#
# "recovered from last night's low after your prune", when the person did not
# prune and a timer did. The assistant cannot see what a person does on a
# box: its own actions are in `assistant_actions` and a human's are
# recorded nowhere, so an action attributed to the reader is invented by
# construction, however many things the pass read first.
#
# "At this rate it'll need another docker prune before evening", or a disk
# forecast to empty within 14 days, drawn from one leg of a sawtooth. A reading
# is evidence; a rate
# drawn through two readings of a series that swings is not, and a prediction
# built on that rate is a guess in the register of a measurement.
#
# Both are stripped unconditionally rather than nudged conditionally, because
# neither becomes true if the pass reads harder.

# An action the reader is said to have taken. "your prune", "after you
# restarted it", "since you fixed". Deliberately narrow: it wants a possessive
# or a pronoun bound to a past action, so "you can prune it" (an offer) and
# "your disk" (a possession) do not match.
_READER_ACTION_RE = re.compile(
    r"\b(?:"
    r"your\s+(?:own\s+)?(?P<noun>prune|restart|reboot|fix|change|deploy|edit|"
    r"cleanup|clean-up|rollback|patch|revert|commit|push|run|reset)\b"
    r"|(?:after|since|once|following)\s+you\s+"
    r"(?P<verb>pruned|restarted|rebooted|fixed|changed|deployed|edited|"
    r"cleaned|rolled back|patched|reverted|committed|pushed|ran|reset)\b"
    r"|you\s+(?:already\s+)?(?P<verb2>pruned|restarted|rebooted|fixed|"
    r"cleaned|rolled back|patched|reverted)\s+it\b"
    r")",
    re.IGNORECASE,
)

# A prediction. The tell is a future claim about a threshold or an action, or
# an explicit rate extrapolation. "at this rate", "will need", "on track to",
# "by evening", "within N days". Past-tense reporting never matches, and
# neither does an offer to do something ("I will check it again at 17:00"),
# because the verb has to attach to a state of the world rather than to the assistant.
_FORECAST_RE = re.compile(
    r"\b(?:"
    r"at (?:this|that) rate"
    r"|on track to\b"
    r"|(?:will|'ll|would|is going to|are going to) (?:be )?"
    r"(?:need|require|run out|fill|empty|exhaust|hit|reach|cross|breach)\b"
    r"|(?:empties|fills|runs out|exhausts)\b[^.!?]{0,30}\bwithin\b"
    r"|\bforecast(?:s|ed|ing)?\b"
    r"|\bproject(?:s|ed|ing)?\b[^.!?]{0,20}\b(?:to|it will|they will)\b"
    r"|\bextrapolat\w+"
    r")",
    re.IGNORECASE,
)


def _claims_a_reader_action(sentence: str) -> bool:
    """Whether this sentence says the reader did something."""
    return bool(_READER_ACTION_RE.search(sentence))


# A prediction stated in the negative, such as "the timer won't schedule
# another run while it's latched" while `systemctl list-timers` shows a NEXT
# run. That is both a prediction and possibly a wrong one, and it is the kind of wrong that changes what a person does. It reads as "you must
# intervene" when the machine would have run it itself.
#
# Kept apart from `_FORECAST_RE` because it needs a subject test that a regex
# alone gets wrong: "I won't send this again" is the assistant's own plan, which it may
# state, and only a claim about the WORLD is unbackable.
_NEGATIVE_FUTURE_RE = re.compile(
    r"\b(?:will not|won't|wo n't|is not going to|are not going to|"
    r"gaat niet|zal niet|zullen niet)\b",
    re.IGNORECASE,
)
_OWN_PLAN_RE = re.compile(
    r"\b(?:i|ik)\s+(?:will not|won't|wo n't|am not going to|zal niet|ga niet)\b",
    re.IGNORECASE,
)


def _forecasts(sentence: str) -> bool:
    """Whether this sentence predicts rather than reports."""
    if _FORECAST_RE.search(sentence):
        return True
    return bool(_NEGATIVE_FUTURE_RE.search(sentence)) and not _OWN_PLAN_RE.search(
        sentence
    )


def reader_action_claim(draft: str) -> str | None:
    """Nudge a draft that credits the reader with an action, else None."""
    hits = [
        sentence
        for sentence in _SENTENCE_SPLIT_RE.split(draft.strip())
        if sentence and _claims_a_reader_action(sentence)
    ]
    if not hits:
        return None
    return (
        "[automatic check, NOT from the person] Your draft says the reader did "
        "something: "
        + " / ".join(one.strip()[:90] for one in hits[:2])
        + ". You cannot see what a person does on that machine; your own "
        "actions are recorded and theirs are not. Say what you observed and "
        "when, and leave out who caused it unless a tool result names them. Do "
        "NOT mention this note; reply as if it never appeared."
    )


def strip_reader_action_claims(draft: str) -> str:
    """Drop the sentences crediting the reader; keep the rest. "" when none
    survive."""
    kept = [
        sentence
        for sentence in _SENTENCE_SPLIT_RE.split(draft.strip())
        if sentence and not _claims_a_reader_action(sentence)
    ]
    return " ".join(kept).strip()


def forecast_claim(draft: str) -> str | None:
    """Nudge a draft that predicts what will happen, else None."""
    hits = [
        sentence
        for sentence in _SENTENCE_SPLIT_RE.split(draft.strip())
        if sentence and _forecasts(sentence)
    ]
    if not hits:
        return None
    return (
        "[automatic check, NOT from the person] Your draft predicts what will "
        "happen: "
        + " / ".join(one.strip()[:90] for one in hits[:2])
        + ". You read a series, not a future. A data disk can swing by twenty "
        "points in a day because a deploy takes scratch space and gives it "
        "back, so a rate drawn through two readings of it is not a measurement "
        "and a prediction built on that rate is a guess wearing the register of "
        "one. Report what you saw and when you saw it, and stop there. Do NOT "
        "mention this note; reply as if it never appeared."
    )


def strip_forecasts(draft: str) -> str:
    """Drop the predicting sentences; keep the rest. "" when none survive."""
    kept = [
        sentence
        for sentence in _SENTENCE_SPLIT_RE.split(draft.strip())
        if sentence and not _forecasts(sentence)
    ]
    return " ".join(kept).strip()


# ── what another person knows (a teammate's session) ──────────────────────
#
# The shape: asked to check a time with somebody, the assistant answers that
# it already did, because it sent them a message, so they know.
#
# Two things wrong in one sentence. Telling somebody is not checking with them.
# And the assistant cannot know that a person knows: it knows a message was
# DELIVERED, which is an audited fact, and reading is not.
#
# Same family as an action credited to the reader: a claim about a person that
# no tool can observe. The assistant's own sends are recorded in `assistant_actions` and it
# may state those precisely, which is what the nudge asks for: "I have sent it
# to them, they have not replied yet" is true, useful and shorter.
#
# Bilingual because chat answers each person in their own language.
_PERSON_KNOWS_RE = re.compile(
    r"\b(?:"
    # English: he knows / she has seen it / they agreed / he is fine with it.
    r"(?:he|she|they" + _TEAM_NAMES + r")\s+"
    r"(?:already\s+)?(?:knows?|is aware|are aware|has seen|have seen|saw it|"
    r"agreed|has agreed|have agreed|approved|is fine with|signed off)\b"
    # Dutch: hij weet ervan / ze is akkoord / hij is op de hoogte.
    r"|(?:hij|zij|ze" + _TEAM_NAMES + r")\s+(?:al\s+)?"
    r"(?:weet\s+(?:het|ervan)|is\s+op\s+de\s+hoogte|is\s+akkoord|"
    r"heeft\s+(?:het\s+)?(?:gezien|goedgekeurd))\b"
    r"|is\s+op\s+de\s+hoogte\b"
    r")",
    re.IGNORECASE,
)

# Answering a request to CHECK with somebody by pointing at a message that was
# merely sent. "I already did" only means what it says if the thing asked for
# was a notification.
_CHECKED_WITH_RE = re.compile(
    r"\b(?:"
    r"(?:i\s+)?(?:have\s+)?already\s+(?:did|done|checked|asked)\b"
    r"|heb\s+ik\s+al\s+gedaan\b"
    r"|dat\s+heb\s+ik\s+al\s+(?:gedaan|gevraagd)\b"
    r")",
    re.IGNORECASE,
)


def _claims_a_person_knows(sentence: str) -> bool:
    """Whether this sentence asserts another person's knowledge or agreement."""
    return bool(_PERSON_KNOWS_RE.search(sentence))


def unverified_person_agreement(draft: str) -> str | None:
    """Nudge a draft that says another person knows or agreed, else None.

    Nudge only, never a strip. Unlike a forecast, the sentence around it is
    usually the answer to the question that was asked, so cutting it would leave
    a reply that reads as a refusal to answer. What is wanted is the same
    sentence with the verifiable half in it.
    """
    hits = [
        sentence
        for sentence in _SENTENCE_SPLIT_RE.split(draft.strip())
        if sentence and _claims_a_person_knows(sentence)
    ]
    if not hits:
        return None
    checked = " You also answered a request to CHECK with somebody by pointing "
    checked += "at a message you sent; telling is not asking."
    return (
        "[automatic check, NOT from the person] Your draft says what another "
        "person knows or has agreed to: "
        + " / ".join(one.strip().rstrip(".!?")[:90] for one in hits[:2])
        + "."
        + (checked if _CHECKED_WITH_RE.search(draft) else "")
        + " You can see that a message was DELIVERED, which is recorded; you "
        "cannot see that it was read, and you never see agreement. Say the part "
        "you can stand behind, that you sent it and when, and whether they have "
        "replied. Do NOT mention this note; reply as if it never appeared."
    )


# ---------------------------------------------------------------------------
# The rules, named, so a guard and a checker cannot drift apart
# ---------------------------------------------------------------------------
#
# Every guard above runs on a DRAFT and may nudge. The weekly claim audit runs
# on what was SENT and may only report. They are the same rules read at two
# different moments, and the whole value of the second is that it is the first:
# a checker with rules of its own would tell you about a message the guards
# were always going to let through, which is a fact about the checker.
#
# Additive on purpose. Not one regex, nudge or strip above changes shape; this
# names the five per-sentence predicates that already exist, so a sixth guard
# added later cannot become a guard without also becoming a checker rule (there
# is a test that fails if it does).


@dataclass(frozen=True)
class SentenceRule:
    """One per-sentence rule, under the name its guard already goes by.

    `holds` is TRUE when the sentence BREAKS the rule, which is the polarity
    every predicate above already has. `says` is the one line a finding prints,
    written for a person reading a weekly report rather than for a model being
    nudged.
    """

    name: str
    says: str
    holds: Callable[[str], bool]


SENTENCE_RULES: tuple[SentenceRule, ...] = (
    SentenceRule(
        "reader_action_claim",
        "says the reader did something, which no reading can show",
        _claims_a_reader_action,
    ),
    SentenceRule(
        "forecast_claim",
        "predicts rather than reports; a reading is not a future",
        _forecasts,
    ),
    SentenceRule(
        "unverified_person_agreement",
        "says what another person knows or agreed to; delivery is recorded, "
        "reading and agreement are not",
        _claims_a_person_knows,
    ),
    SentenceRule(
        "green_telemetry",
        "reads out healthy numbers nobody acts on",
        _is_green_telemetry,
    ),
    SentenceRule(
        "own_plumbing",
        "reports openclaw's own bookkeeping rather than something the reader "
        "acts on",
        _is_own_plumbing,
    ),
)


def unread_stamp(sentence: str, evidence: str) -> bool:
    """True when the sentence carries a date, clock time or number that no
    recorded reading contains.

    CHECKER-ONLY, and that is a design decision rather than an oversight. As a
    draft guard it would fire on legitimate arithmetic: "between 12:19 and
    13:01" is a relation computed from two rendered timestamps, which the house rules
    clause 4 asks for by name, and neither number need appear in a reading in
    that form. What makes it safe AFTER the fact is that a person reads the
    finding and decides.

    It is the one rule no existing guard covers. A beat can say a unit has
    been "stuck in failed state since ~09:35 UTC" when the unit failed hours
    earlier and `systemctl list-timers` said so. `_QUANTITY_CLAIM_RE` needs a
    unit word or an ISO date and a bare clock time is neither, so every other
    guard on that road stays quiet.

    With NO evidence recorded it returns False, deliberately. Nothing before
    this ships has readings behind it, and reading "no evidence" as "the stamp
    is invented" would flag every message ever sent. Same benefit of the doubt
    `_restates_grounded` gives, for the same reason.
    """
    if not evidence.strip():
        return False
    tokens = _tokens_in(sentence)
    if not tokens:
        return False
    return any(token not in evidence for token in tokens)
