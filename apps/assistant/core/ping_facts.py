"""Typed facts out of a raw notify-pen ping.

Handing the whole ping body to the writer and asking it for a page can
produce a sentence whose every noun is present in an unstructured body and
whose claim is not: the body is the evidence and the prose is free. This module is the other half of the fix. It reads the body
ONCE, here, in code with no model and no SDK, and everything downstream may
only say what a typed field on `PingFact` carries.

Three rules hold the whole module up.

1. A shape this module cannot read is `kind="passthrough"` carrying the fields
   it did get. That is the correct answer, not a failure: an unreadable body
   yields fewer facts, never invented ones.

2. A field is filled only from what the SENDER wrote about THIS ping, which is
   the subject plus the lines of the body that are the sender's own. Quoted
   output is not the sender writing: a `journalctl -u <unit> -n 30` tail is
   thirty lines of whatever processes logged inside a window scoped by line
   count and not by run, so `_sender_lines` drops the lines that carry the
   `<timestamp> <host> <process>[<pid>]:` prefix `journalctl
   --output=short-iso` stamps on each entry, and no field is filled with what
   such a line SAYS. That is the one journal format any sender here quotes;
   a tail in the default format, a continuation line of a multi-line entry and
   a line with no `[pid]` are not stripped, and nothing sends one today. Their
   presence is read once and for one thing: a body quoting a window is a body
   the sender cut, which is `body_complete`. What is left of the body is read
   as it stands. Nothing ranks, guesses or summarises.

3. A history that was not read is its own state. `History.state == "unknown"`
   can never be confused with a genuine first sighting, which is
   `state == "known"` with `seen_count == 1`. `seen_count` is the number the
   source actually gave; 0 means no count is known, whether because nobody
   looked or because the source answered without one. There is no floor
   raising a missing count to 1, because 1 is the exact value that licenses
   "the first ping on this subject". Conflating the two is the house rules,
   and it is the specific bug this dataclass exists to make unexpressible.

Three fields a body cannot fill, and why empty is the answer. `error_line`,
`runbook` and `qualifier` are the sentences a page most wants, and they are the
ones no reading of a body can support. An error line read from under a
`<tool> error:` label is the sender marking the LABEL and not the line:
"token EXAMPLEKEYID <secret> is invalid" is a body line like any other, and the
scan senders redact their findings precisely so that no page can carry a
credential. A runbook taken from any line whose first word is a command name
and none of whose words are English prose would hand a reader a sentence like
"systemctl status example crashed overnight" to type. A qualifier matched from
a list of English hedge words anywhere in the subject plus body is not the
sender hedging but a word search: in "secret scan found a possible committed
secret", "possible" is an adjective inside the sender's own noun phrase, not
a hedge. None of the three questions is answerable in English: only the
sender knows which of its lines is its error message, which is an instruction,
and whether it hedged at all.

So none of the three is read out of a body, and the sentences come back the
only way they honestly can: the sender says so in a field of its own. A ping
may carry a `facts` object its sender wrote, and `marked` lays that over what
the body gave, which is what `_fact` builds every fact through. Five fields
take a marking, and they are the five a sender knows and a body cannot say:
`error_line`, `runbook` and `qualifier`, which no body fills at all, plus
`exit_code` and `blocks_deploy`, where a sender that says so outranks the
prose the parser would otherwise read it out of.

TYPED HERE, NOT AT THE GATE. The webhook checks that a `facts` value is an
object and stores it as the sender wrote it; which keys exist and what they
have to be is this module's, because this is where the rule that nothing may
be said except from a typed field is kept, and a second copy of the vocabulary
at the boundary is a second copy to drift. Everything about the reading is
therefore per field: a marking that is not readable is not a marking, an
unknown key is dropped, and a field this module cannot type falls back to the
body underneath it exactly as if the sender had marked nothing. A half-typed
sender degrades one field at a time; it never costs the ping.

The same refusal covers the journal tail. `systemd_failure_notify` runs
`journalctl -u <unit> -n 30` with no invocation scoping, so the window can hold
six runs of a five-minute unit and not one line of the failing one. Counting the failures in the tail does not find the boundary, because
the ordinary window holds successful runs too, and no count of prose lines can
prove a window covers exactly one invocation. So a tail is not read at all: the
counted numbers and every other field come from the sender's own lines, and a
`unit_failed` ping whose body is all tail carries its host, its unit and its
history and nothing more.

`bundle` takes its history source as an argument so the tests can stub it, and
so this module never opens a database. The source is called with the RAW ping
subject: `notify_flush._subject_for_audit` owns the normalisation the audit and
the two mutes are written against, and duplicating it here would let the two
drift. What DOES live here is the reading underneath that normalisation,
`split_subject`, so the audit key and the page text are cut from one string by
one rule.

FAILURE POLICY: Tier-2 degrade, never drop. No parser here can raise a batch:
an unreadable field is None, an unreadable body is `passthrough`, and a history
source that raises is `unknown`. Nothing in this module writes.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any, Literal

from apps.assistant.core import state as _state

log = logging.getLogger("openclaw.ping_facts")

KINDS = frozenset(
    {
        "unit_failed",
        "deploy_step_failed",
        "gate_red",
        "secret_scan_hit",
        "counter_rose",
        "drift",
        "probe_failed",
        "passthrough",
    }
)


@dataclass(frozen=True)
class Parsed:
    """What the body said, field by field. Every one is nullable on purpose.

    `error_line`, `runbook` and `qualifier` are never filled from a body: no
    reading of English says which line a sender meant as its error message, as
    an instruction to run, or as a hedge on its own finding. A sender that says
    so in a field of its own fills them through `marked`; a sender that does
    not leaves them empty, and the page carries none of those sentences.

    `must_page` is the odd one out and is about ROUTING, not about the thing
    that happened: a sender setting it says this page cannot wait for the
    morning and cannot be judged into silence. No body fills it, and unlike
    every other field here it never reaches the prompt block, because what the
    page SAYS is still the model's call. Only whether one goes out stops being.
    """

    host: str | None
    unit: str | None
    sha: str | None
    exit_code: int | None
    error_line: str | None
    counts: tuple[tuple[str, int], ...]
    log_path: str | None
    runbook: tuple[str, ...]
    qualifier: str | None
    blocks_deploy: bool | None
    must_page: bool | None


#: How a person says a count, for `History.nth_time`. Written out to ten and
#: then "11th": past about ten the exact number stops being the point and the
#: fact that it keeps happening is. One table per language the catalogue
#: writes, because an ordinal is a word and not a number with a suffix rule
#: that survives translation.
_ORDINALS_NL = {
    2: "Tweede",
    3: "Derde",
    4: "Vierde",
    5: "Vijfde",
    6: "Zesde",
    7: "Zevende",
    8: "Achtste",
    9: "Negende",
    10: "Tiende",
}

_ORDINALS = {
    2: "Second",
    3: "Third",
    4: "Fourth",
    5: "Fifth",
    6: "Sixth",
    7: "Seventh",
    8: "Eighth",
    9: "Ninth",
    10: "Tenth",
}


@dataclass(frozen=True)
class History:
    """How often this subject has come past, or the fact that nobody looked.

    `seen_count` counts PINGS, not incidents and not events: one row in the pen
    is one ping. It is 0 whenever no count is known, which covers every unknown
    history and also a read one whose source gave no usable number, so neither
    can be read as the 1 that means a first sighting.
    """

    state: Literal["known", "unknown"]
    seen_count: int
    first_seen_at: str | None
    last_delivered_at: str | None
    changed_tokens: tuple[str, ...]

    @property
    def nth_time(self) -> str | None:
        """"Second", "Third", "11th": the count as a person would say it.

        `seen_count` reached a page as the bare number in "Ping 2 on this
        subject", which is this system counting its own rows out loud. A
        reader cannot tell what it is for: the number is pings inside a fortnight, so it answers a question
        nobody asked and invites one nobody can answer from the page.

        What a reader wants from a count is whether this is new or a repeat,
        so it is said in words and only where it means something. None below
        two, which drops the sentence holding it: 0 is "nobody looked" and 1 is
        a first sighting, and `first_seen` already has its own line for that.
        """
        if self.state != "known" or self.seen_count < 2:
            return None
        return _ORDINALS.get(self.seen_count, f"{self.seen_count}th")

    @property
    def nth_time_nl(self) -> str | None:
        """`nth_time` for the Dutch catalogue. Same rule, Dutch words."""
        if self.state != "known" or self.seen_count < 2:
            return None
        return _ORDINALS_NL.get(self.seen_count, f"{self.seen_count}e")


@dataclass(frozen=True)
class PingFact:
    """One pen row, reduced to the fields anything downstream may speak from.

    Two spellings of the subject, on purpose. `subject` is the sender's own
    string and is what every lookup is keyed on: the severity marker is read
    off it, the audit row is cut from it and both mutes match on it.
    `display_subject` is the same subject with that marker and the product
    banner off, and it is the only one a page prints. Deriving it once here,
    after the severity has been read, is what keeps the two from disagreeing:
    stripped at render time instead, the page and the floor's own list of
    subjects were cut by different rules and the floor stopped recognising its
    own lead.
    """

    ping_id: int
    kind: str
    subject: str
    display_subject: str
    source: str
    severity: str
    observed_at: str
    parsed: Parsed
    body_complete: bool
    history: History

    @property
    def finding_commit(self) -> str | None:
        """The short commit a secret-scan finding is about, None for any other
        ping.

        The scan sends one page per commit under one fixed subject, so the
        commit is the only thing that tells two findings apart. Every
        other kind keeps its sha off the page, as `page_render.DETAILS` says.
        """
        if self.kind != "secret_scan_hit" or not self.parsed.sha:
            return None
        return self.parsed.sha[:7]


UNKNOWN_HISTORY = History(
    state="unknown",
    seen_count=0,
    first_seen_at=None,
    last_delivered_at=None,
    changed_tokens=(),
)


# ---------------------------------------------------------------------------
# The subject, and the furniture in front of it
# ---------------------------------------------------------------------------

# The product banner some senders put in front of the subject. Constant, so it
# carries nothing: the reader has one product, and on a phone it is 13
# characters of header before the first word of news. Lives here rather than in
# `notify_flush` because the audit key and the page text are cut from the same
# string, and two copies of this rule would drift apart the first time one of
# them was tuned.
_SUBJECT_BANNER_RE = re.compile(r"^\s*(?:\[[^\]]+\]\s*)?")

# The marker a sender writes in front of its subject, found by POSITION rather
# than by looking it up. `state.SEVERITY_MARKERS` says what a marker MEANS, and
# a table of meanings can fall one sender behind. If the lookup also FOUND the
# marker, an unlisted one would stop the split dead, and the banner strip
# behind it would then run against a string beginning with an emoji, where
# `^\s*\[` matches zero characters, leaving "[the project] " on the subject.
#
# A leading run of non-ASCII characters holding no letter, which on this
# surface is furniture and nothing else: every subject in the stack is English
#, so the first word of the news is always ASCII. Matching by
# unicode category instead would be narrower and wrong, because the variation
# selector that trails half these emoji is a combining mark. The no-letter
# clause is what keeps a word like "Überprüfung" from losing its first letter
# to a page; a marker that IS a letter (the information sign is one) should fail
# loudly instead of quietly keeping its banner.
_LEADING_MARKER_RE = re.compile(r"^([^\x00-\x7f]+)\s*")


def _leading_marker(text: str) -> str:
    """The marker in front of the subject, or "" when there is none."""
    found = _LEADING_MARKER_RE.match(text)
    if not found or any(char.isalpha() for char in found.group(1)):
        return ""
    return found.group(1)


def split_subject(subject: str) -> tuple[str, str]:
    """A subject as (the marker the sender wrote, the rest of it).

    The rest has the marker and the product banner off, in that order and
    whether or not `state.SEVERITY_MARKERS` recognises the marker. Recognising
    it is a question about severity and is asked separately; conflating the two
    is what left the banner standing on every subject carrying a marker nobody
    had listed yet. The marker is handed back rather than thrown away, because
    it is the only per-subject severity anyone records and the audit row keeps
    it (`notify_flush._subject_for_audit`).

    Both halves are read HERE, before anything downstream sees the subject, so
    a page, an audit row and a severity all cut the same string the same way.
    """
    text = str(subject or "").strip()
    marker = _leading_marker(text)
    if marker:
        text = text[len(marker):].lstrip()
    return marker, _SUBJECT_BANNER_RE.sub("", text).strip()


#: How much of a subject's text a mute key keeps. The audit row cuts marker,
#: space and text together at `notify_flush._SUBJECT_CHARS` (90), so a marked
#: spelling keeps up to three characters less text than the bare one. Cutting
#: the key below both is what lets the two spellings of one long subject meet.
MUTE_KEY_CHARS = 86


def mute_key(subject: str) -> str:
    """The one key a filed mute is written, looked up and refused under.

    The text of the subject with the sender's marker and the product banner
    off. The marker has to go because it is not part of WHAT happened: when
    a card is filed under "auto-deploy: a commit was reverted
    on main" from a row that carried no marker and every later ping arrives as
    "🔴 auto-deploy: ...", an exact match on the marked audit spelling
    never finds the mute. The severity the marker carries is read separately,
    by `state.severity_of_subject`, from the spelling the sender wrote.
    """
    return split_subject(subject)[1][:MUTE_KEY_CHARS].rstrip()


def display_subject(subject: str) -> str:
    """The subject as page text: severity marker and product banner off.

    A page is a sentence, not a header. The severity is a typed field on the
    fact and the reader has one product, so neither belongs in front of the
    news; `PingFact.subject` still carries the sender's own string for every
    lookup that is keyed on it.

    A subject that is nothing BUT furniture comes back as the sender wrote it:
    an empty subject drops the sentence holding it, and no page is better than
    an ugly one.
    """
    _marker, text = split_subject(subject)
    return text or str(subject or "").strip()


# ---------------------------------------------------------------------------
# Kind
# ---------------------------------------------------------------------------

# Read against the SUBJECT only, in this order, first hit wins. The order is
# load-bearing: "auto-deploy: verification gate RED" is a gate verdict before
# it is a deploy step, and "auto-deploy: sdk probe venv missing" is a probe.
_KIND_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("unit_failed", re.compile(r"systemd unit failed", re.IGNORECASE)),
    ("gate_red", re.compile(r"verification gate", re.IGNORECASE)),
    ("secret_scan_hit", re.compile(r"secret scan", re.IGNORECASE)),
    (
        "counter_rose",
        re.compile(r"count rose|rose above|found vulnerabilit", re.IGNORECASE),
    ),
    ("probe_failed", re.compile(r"\bprobe\b|\bcanary\b", re.IGNORECASE)),
    (
        "drift",
        re.compile(
            r"\bdrift\b|\bmismatch\b|out of sync|is behind|\bstale\b|is a lie",
            re.IGNORECASE,
        ),
    ),
    ("deploy_step_failed", re.compile(r"auto-deploy", re.IGNORECASE)),
)


def kind_of(subject: str) -> str:
    """Which of `KINDS` this subject announces; "passthrough" when none."""
    head = str(subject or "")
    for kind, pattern in _KIND_RULES:
        if pattern.search(head):
            return kind
    return "passthrough"


# ---------------------------------------------------------------------------
# Field parsers. One body shape family each, all of them nullable.
# ---------------------------------------------------------------------------

_HOST_RE = re.compile(r"^Host:[ \t]*(\S.*?)\s*$", re.MULTILINE)
_UNIT_LINE_RE = re.compile(r"^Unit:[ \t]*(\S.*?)\s*$", re.MULTILINE)
_UNIT_SUBJECT_RE = re.compile(r"systemd unit failed:[ \t]*(\S+)", re.IGNORECASE)
_SHA_RE = re.compile(r"\bSHA[:\s]\s*([0-9a-f]{7,40})\b", re.IGNORECASE)
_LOG_PATH_RE = re.compile(r"(/[\w./@+-]*\.log)\b")

# An exit code counts only where the sender labelled one. The `status=1/FAILURE`
# lines of a journal tail never reach here: `_sender_lines` drops them, because
# they belong to whichever invocation happened to sit in the 30-line window,
# which is not necessarily the one that paged.
_EXIT_CODE_RES = (
    re.compile(r"\brc=(-?\d+)"),
    re.compile(r"\bexit[ _]code:?\s*(-?\d+)", re.IGNORECASE),
)

# The line shape `journalctl --output=short-iso` prints. A body carrying these
# is quoting a window scoped by line count rather than by run, so the lines in
# it belong to however many invocations happened to fit.
_JOURNAL_LINE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\S+\s+\S+\s+\S+?\[\d+\]:")


def _carries_journal_output(body: str) -> bool:
    """Whether the body quotes short-iso journal lines, whoever logged them."""
    return any(_JOURNAL_LINE_RE.match(line) for line in body.splitlines())


def _sender_lines(body: str) -> str:
    """The body with its quoted short-iso journal lines removed.

    What is left is what the sender wrote about THIS ping: its own headers, its
    own sentences, its own counted numbers. A journal line is output of
    whatever ran inside a window the sender scoped by line count, so it can
    belong to a run hours before the one that paged, and no reading of the tail
    separates the two: the ordinary window holds successful runs as well, so
    counting failures does not find the boundary either. Every parser of a
    `Parsed` field reads this rather than the body, which is why a body that is
    nothing but a tail yields nothing at all.

    Only the `--output=short-iso` shape is stripped, because it is the shape
    the one journal-quoting sender emits (`systemd_failure_notify`). A sender
    quoting another journal format would hand its lines to the parsers below,
    and the answer then is to type that sender rather than to widen this.
    """
    return "\n".join(
        line for line in body.splitlines() if not _JOURNAL_LINE_RE.match(line)
    )


def _host(text: str) -> str | None:
    """The host the sender named on its own `Host:` line."""
    match = _HOST_RE.search(text)
    return match.group(1) if match else None


def _unit(subject: str, text: str) -> str | None:
    """The systemd unit, from the sender's `Unit:` line or from the subject."""
    match = _UNIT_LINE_RE.search(text)
    if match:
        return match.group(1)
    match = _UNIT_SUBJECT_RE.search(subject)
    return match.group(1) if match else None


def _sha(subject: str, text: str) -> str | None:
    """The commit the sender stamped on the ping, labelled as a SHA."""
    match = _SHA_RE.search(text) or _SHA_RE.search(subject)
    return match.group(1) if match else None


def _exit_code(text: str) -> int | None:
    """The exit status the sender labelled, or None when it labelled none."""
    for pattern in _EXIT_CODE_RES:
        match = pattern.search(text)
        if match:
            return int(match.group(1))
    return None


def _log_path(text: str) -> str | None:
    """The log file the sender pointed at, when it named a path at all.

    The secret-scan bodies say "full pointers in the scan log on the VM" and
    name no path, which is why this is nullable rather than a best guess.
    """
    match = _LOG_PATH_RE.search(text)
    return match.group(1) if match else None


# Numbers the senders count out loud. Each entry names the counts one pattern
# yields, in the order they should appear on a page.
_COUNT_RULES: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (
        re.compile(r"count rose \((\d+) > baseline (\d+)\)", re.IGNORECASE),
        ("findings", "baseline"),
    ),
    (re.compile(r"previously reported at (\d+)", re.IGNORECASE), ("previously",)),
    (re.compile(r"leaks found:\s*(\d+)", re.IGNORECASE), ("leaks",)),
    (re.compile(r"Found (\d+) errors?\b", re.IGNORECASE), ("errors",)),
    (re.compile(r"^Attempts:\s*(\d+)/(\d+)", re.IGNORECASE | re.MULTILINE),
     ("attempt", "attempts")),
    (re.compile(r"(\d+) commits scanned", re.IGNORECASE), ("commits",)),
    (re.compile(r"for (\d+) cycles", re.IGNORECASE), ("cycles",)),
)


def _counts(subject: str, text: str) -> tuple[tuple[str, int], ...]:
    """The numbers the sender counted, in the order the rules name them.

    A rule contributes all of its numbers or none of them, so a pair like
    "attempt 3 of 3" stays a pair, and a rule whose numbers are all already on
    the list is dropped: a ruff body says 191 in its subject and again in its
    tail, and the same number under two names reads as two facts.

    There is no count of how many runs a journal tail spans. Counting the
    failures in it counted failures and was rendered as invocations, and the
    number a page most wants here, how many of the runs in the window are the
    one that paged, is not in the window at all.
    """
    haystack = f"{subject}\n{text}"
    found: list[tuple[str, int]] = []
    for pattern, names in _COUNT_RULES:
        match = pattern.search(haystack)
        if not match:
            continue
        pairs = [(name, int(value)) for name, value in zip(names, match.groups())]
        known_values = {value for _name, value in found}
        if all(value in known_values for _name, value in pairs):
            continue
        found.extend(pair for pair in pairs if pair[0] not in {n for n, _ in found})
    return tuple(found)


# Whether the deploy stopped is carried entirely in prose today. Both halves are
# read, and the "kept going" phrases are read first because they are the more
# specific sentences.
_DEPLOY_CONTINUED = (
    "was not blocked",
    "deploy continued",
    "deploys continued",
    "nothing is blocked",
    "never a deploy",
    "deploys are unaffected",
    "costs build minutes",
)
_DEPLOY_BLOCKED = (
    "deploys skipped",
    "deploys now skipped",
    "deploys are skipped",
    "deploy skipped",
    "deploys blocked",
    "nothing can ship",
)


def _blocks_deploy(subject: str, text: str) -> bool | None:
    """Whether the sender said the deploy stopped; None when it said neither."""
    haystack = f"{subject}\n{text}".lower()
    if any(phrase in haystack for phrase in _DEPLOY_CONTINUED):
        return False
    if any(phrase in haystack for phrase in _DEPLOY_BLOCKED):
        return True
    return None


# Every marker below means the sender handed over a cut window rather than the
# whole story, either because it ran a `tail` itself or because its reader gave
# up, for instance when `journalctl` times out.
_TRUNCATION_MARKERS = (
    "tail:",
    "tail (",
    "journal lines:",
    "journalctl invocation failed",
    "-- no entries --",
    "(empty journal)",
)
# Each marker has to START a word. As free substrings, "tail:" sits inside
# "Details:", which is the heading of every cloud CLI error, so a sender
# that handed over its whole body was reported as having cut it short.
_TRUNCATION_RES = tuple(
    re.compile(r"(?<!\w)" + re.escape(marker), re.IGNORECASE)
    for marker in _TRUNCATION_MARKERS
)


def _body_complete(body: str) -> bool:
    """Whether the body is the whole story the sender had.

    False is a claim about the SENDER's behaviour and it leads the page, so it
    is made only where a marker really begins, or where the body quotes journal
    output, which is a cut window by construction: `journalctl -n 30` hands
    over thirty lines and drops whatever else the unit logged.
    """
    if _carries_journal_output(body):
        return False
    return not any(pattern.search(body) for pattern in _TRUNCATION_RES)


def parse(subject: str, body: str) -> Parsed:
    """Every typed field one ping body yields.

    Read from the subject and the sender's own lines. `error_line`, `runbook`
    and `qualifier` are left empty by every route through here: a body cannot
    say which of its lines the sender meant as its error message, as an
    instruction, or as a hedge on its own finding, so this parser does not
    answer those questions at all. `marked` is where a sender's own answer
    goes, over the top of this one.
    """
    text = _sender_lines(body)
    return Parsed(
        host=_host(text),
        unit=_unit(subject, text),
        sha=_sha(subject, text),
        exit_code=_exit_code(text),
        error_line=None,
        counts=_counts(subject, text),
        log_path=_log_path(text),
        runbook=(),
        qualifier=None,
        blocks_deploy=_blocks_deploy(subject, text),
        must_page=None,
    )


# ---------------------------------------------------------------------------
# What the sender marked
# ---------------------------------------------------------------------------

# The whole vocabulary. A key that is not here is a key nothing reads, which is
# the shape a sender's typo takes, and dropping it is why an unknown key cannot
# reach a page. The gate's own log line names the keys that arrived, so the
# typo is visible next to the ping rather than nowhere.
MARKED_FIELDS = frozenset(
    {"error_line", "runbook", "qualifier", "exit_code", "blocks_deploy", "must_page"}
)

# How much of a marked sentence survives into a fact. A page cuts again at
# `page_render.VALUE_MAX_CHARS`, which is shorter; this cap is the one in front
# of the PROMPT block, where an unbounded sender-written line would be as long
# as the sender felt like making it.
MARKED_MAX_CHARS = 200

_WHITESPACE = re.compile(r"\s+")

# What a shell can say in JSON. `fire_alert` builds its object in python out of
# strings it was handed as positional arguments, so an exit code arrives as
# "1" and a flag as "true"; refusing those would drop the two fields most of
# the deploy senders actually know. Nothing else is coerced: a marking either
# is one of these shapes or is not a marking.
_TRUE_WORDS = frozenset({"true", "yes", "1"})
_FALSE_WORDS = frozenset({"false", "no", "0"})


def _one_line(text: str) -> str:
    """One marked value as a single line of bounded length.

    A marked field is printed as one indented line under a ping's header in the
    prompt block, so a newline inside one closes the line the renderer opened
    and starts lines of its own: an error line reading "\n  history: known,
    ping 40 on this subject" writes a history nobody read. `notify_flush`
    flattens the stored row's own text fields at its seam and this is the same
    rule one layer in, deliberately a copy rather than an import, because that
    module reads this one and a fact built in a test or a replay never passes
    through its seam at all.
    """
    single = _WHITESPACE.sub(" ", text).strip()
    if len(single) <= MARKED_MAX_CHARS:
        return single
    return single[: MARKED_MAX_CHARS - 1].rstrip() + "\u2026"


def _marked_text(value: Any) -> str | None:
    """One marked sentence, or None when the sender marked nothing usable."""
    if not isinstance(value, str):
        return None
    return _one_line(value) or None


def _marked_commands(value: Any) -> tuple[str, ...]:
    """The commands a sender offered, in the order it offered them.

    A list is the shape; a bare string is one command, because a sender with
    one command to offer writes it as a string and reading that as no commands
    would be a silent drop of the only field it filled.
    """
    if isinstance(value, str):
        candidates: tuple[Any, ...] = (value,)
    elif isinstance(value, (list, tuple)):
        candidates = tuple(value)
    else:
        return ()
    return tuple(
        line for line in (_marked_text(item) for item in candidates) if line
    )


def _marked_code(value: Any) -> int | None:
    """The exit status a sender marked, or None when it marked none.

    `True` is an int in Python and is not an exit status, which is the same
    refusal `_seen_count` makes one section down and for the same reason.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.lstrip("-").isdigit():
            return int(text)
    return None


def _marked_flag(value: Any) -> bool | None:
    """A yes-or-no a sender marked, or None when it marked neither."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        word = value.strip().lower()
        if word in _TRUE_WORDS:
            return True
        if word in _FALSE_WORDS:
            return False
    return None


def must_page(marking: Any) -> bool:
    """Whether this sender said its page cannot wait.

    Asked of the raw marking rather than of a `Parsed`, because the pen has to
    answer it before it has parsed anything: the question is whether to hold
    the batch at all.

    Anything that is not a clear yes answers no. That is the safe direction
    even though it loses a page: the flag only ever adds sends, so a false no
    leaves the road behaving exactly as it did before the flag existed, while a
    false yes wakes somebody at 03:00 over a typo.
    """
    if not isinstance(marking, Mapping):
        return False
    return _marked_flag(marking.get("must_page")) is True


def marked(parsed: Parsed, marking: Any) -> Parsed:
    """What the sender marked, laid over what the body said.

    Field by field, and only the six in `MARKED_FIELDS`. A field the sender
    marked replaces the body's answer, which is the whole point of the object:
    the sender knows and the parser was guessing. A field it did not mark, or
    marked in a shape this module cannot type, leaves the body's answer exactly
    where it was, so a sender halfway through being typed reads as the sender
    it was for everything it has not got to yet.
    """
    if not isinstance(marking, Mapping):
        return parsed
    changes: dict[str, Any] = {}
    error_line = _marked_text(marking.get("error_line"))
    if error_line is not None:
        changes["error_line"] = error_line
    qualifier = _marked_text(marking.get("qualifier"))
    if qualifier is not None:
        changes["qualifier"] = qualifier
    runbook = _marked_commands(marking.get("runbook"))
    if runbook:
        changes["runbook"] = runbook
    exit_code = _marked_code(marking.get("exit_code"))
    if exit_code is not None:
        changes["exit_code"] = exit_code
    blocks_deploy = _marked_flag(marking.get("blocks_deploy"))
    if blocks_deploy is not None:
        changes["blocks_deploy"] = blocks_deploy
    must_page = _marked_flag(marking.get("must_page"))
    if must_page is not None:
        changes["must_page"] = must_page
    return replace(parsed, **changes) if changes else parsed


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

HistorySource = Callable[[str], Mapping[str, Any] | None]


def _tokens(value: Any) -> tuple[str, ...]:
    """A history source's `changed_tokens` as a tuple of non-empty strings."""
    if isinstance(value, str) or not isinstance(value, (list, tuple, set)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _seen_count(value: Any) -> int:
    """The count a source gave, or 0 when it gave nothing usable.

    A word, a negative, a zero and a missing key all mean the same thing here:
    this source did not count. `True` is an int in Python and is not a count.
    """
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return 0


def _known_history(record: Mapping[str, Any]) -> History:
    """A history that was actually read, turned into the typed record.

    The read is what makes the state "known"; the count is a separate fact and
    a source that gave none leaves it at 0. There is deliberately no floor:
    raising a missing count to 1 lands on the one value that licenses "the
    first ping on this subject", which is the house rules reached through a
    `max()` inside the module whose whole job is to make that unexpressible.
    """
    return History(
        state="known",
        seen_count=_seen_count(record.get("seen_count")),
        first_seen_at=record.get("first_seen_at") or None,
        last_delivered_at=record.get("last_delivered_at") or None,
        changed_tokens=_tokens(record.get("changed_tokens")),
    )


def history_for(subject: str, history_of: HistorySource) -> History:
    """This subject's history, or the explicit fact that it was not read.

    A source that raises, answers None, answers empty, or answers something
    that is not a mapping all land on the same "unknown", and "unknown" is
    never rendered as a first occurrence.
    """
    try:
        record = history_of(subject)
    except Exception as exc:  # noqa: BLE001, Tier-2: an unread history is a state
        log.warning("ping history read failed for %r: %s", subject, exc)
        return UNKNOWN_HISTORY
    if not isinstance(record, Mapping) or not record:
        return UNKNOWN_HISTORY
    return _known_history(record)


# ---------------------------------------------------------------------------
# The bundle
# ---------------------------------------------------------------------------


def _fact(ping: Mapping[str, Any], history_of: HistorySource) -> PingFact:
    """One pen row as a `PingFact`, its sender's own marking ahead of its body.

    A row with no `facts` key is the ordinary case and reads exactly as it did
    before senders could mark anything.
    """
    subject = str(ping.get("subject") or "")
    body = str(ping.get("body") or "")
    kind = kind_of(subject)
    return PingFact(
        ping_id=int(ping["id"]),
        kind=kind,
        subject=subject,
        # Severity off the RAW subject first, then the display spelling: the
        # marker is what carries the severity, so a page that never shows it
        # still ranks by it.
        display_subject=display_subject(subject),
        source=str(ping.get("source") or ""),
        severity=_state.severity_of_subject(subject),
        observed_at=str(ping.get("received_at") or ""),
        parsed=marked(parse(subject, body), ping.get("facts")),
        body_complete=_body_complete(body),
        history=history_for(subject, history_of),
    )


def bundle(pings: list[dict], *, history_of: HistorySource) -> tuple[PingFact, ...]:
    """The whole unflushed batch as typed facts, in the order it arrived.

    `history_of` is injected rather than imported so this module opens no
    database and the tests can stub the three outcomes that matter: a source
    that raises, one that knows nothing, and one that knows a count.
    """
    return tuple(_fact(ping, history_of) for ping in pings)


# ---------------------------------------------------------------------------
# The prompt block
# ---------------------------------------------------------------------------

_PREAMBLE = (
    "System pings, one block each. Every line is a field read out of the ping "
    "by code; the raw bodies are not here and are not available to you. A "
    "field that is absent was not in the ping, and you may not supply it."
)


def _labelled(label: str, value: Any) -> str | None:
    """One `label: value` line, or None when the field carries nothing."""
    if value is None or value == "" or value == ():
        return None
    return f"  {label}: {value}"


def _count_lines(counts: tuple[tuple[str, int], ...]) -> str | None:
    """The counted numbers as one line."""
    if not counts:
        return None
    return "  counted: " + "; ".join(f"{name} {value}" for name, value in counts)


def _history_line(history: History) -> str:
    """The history as one line that cannot be read as the wrong state."""
    if history.state == "unknown":
        return "  history: not read, so nothing is known about earlier pings"
    counted = (
        f"known, ping {history.seen_count} on this subject"
        if history.seen_count
        else "read, but the store gave no count of earlier pings"
    )
    parts = [counted]
    if history.first_seen_at:
        parts.append(f"first at {history.first_seen_at}")
    if history.last_delivered_at:
        parts.append(f"last delivered at {history.last_delivered_at}")
    if history.changed_tokens:
        parts.append("changed since the last one: " + ", ".join(history.changed_tokens))
    return "  history: " + "; ".join(parts)


def _fact_block(fact: PingFact) -> str:
    """One fact as the lines the model is allowed to read."""
    parsed = fact.parsed
    lines = [
        f"ping {fact.ping_id} [{fact.kind}] {fact.severity}",
        f"  subject: {fact.subject}",
        f"  source: {fact.source}",
        f"  observed at: {fact.observed_at}",
    ]
    optional = (
        _labelled("host", parsed.host),
        _labelled("unit", parsed.unit),
        _labelled("commit", parsed.sha),
        _labelled("exit code", parsed.exit_code),
        _labelled("error line the sender marked", parsed.error_line),
        _count_lines(parsed.counts),
        _labelled("log path", parsed.log_path),
        _labelled("commands the sender offered", "; ".join(parsed.runbook)),
        _labelled("the sender's own hedge", parsed.qualifier),
    )
    lines.extend(line for line in optional if line)
    if parsed.blocks_deploy is not None:
        stopped = "yes" if parsed.blocks_deploy else "no"
        lines.append(f"  the sender says this stops the deploy: {stopped}")
    if not fact.body_complete:
        lines.append("  the sender handed over a cut window, not the whole story")
    lines.append(_history_line(fact.history))
    return "\n".join(lines)


def render(facts: tuple[PingFact, ...]) -> str:
    """The prompt block for one batch. No raw ping body ever reaches it."""
    if not facts:
        return "No pings in this batch."
    blocks = [_fact_block(fact) for fact in facts]
    return _PREAMBLE + "\n\n" + "\n\n".join(blocks)
