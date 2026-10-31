"""Collect-think-summarise for system pings, the notify pen's flusher
(collect the alerts, think about them, send summaries).

The gate drops every `/webhook/notify` ping in `state.notify_pen`;
nothing pages per ping anymore. `flush_pen()` runs on a short interval
(in-container daemon thread, same single-volume reason as the monitor runner) and,
when there is something to say AND the story-pacing gap has passed,
makes ONE LLM call over the whole unflushed batch plus what openclaw recently
told the recipient, so a crash-looping unit becomes one page about a story
rather than a page per failure. The message goes out via the normal Signal
path and lands in outbound memory like everything else.

A page says what broke and stops. No suggested command: reading one out of a
free-text ping body is a guess, and it belongs to typed senders. Not a cause
either: nothing on this path ran a check, so any cause would be a guess. Not
what it could not read, not an offer to open an issue, not a question about
what to do next.

Pacing: a lone ping in a calm period flushes on the next tick (fast
first signal, ≤~30 s added latency); once something has been sent, the
pen holds further pings until `STORY_GAP_SECONDS` has passed, then
summarises everything that piled up. Silence costs nothing: a batch judged to
be a repeat of something already said clears the pen with no message.

THE MESSAGE IS NOT WRITTEN BY THE MODEL. `ping_facts.bundle` reads
each ping body once, in Python, into typed fields; the model gets those fields
and one terminal tool whose input is a SELECTION (which ping leads, which
aspect of it is the news, which others ride along and how they relate);
`page_render`
renders that selection through sentences a person wrote, in the reader's own
language. `flush_pen` reads the tool input and nothing else, so no
model-authored prose reaches Signal and the raw ping body never enters the
prompt at all. That is the house rules, and it replaces the older grounding
argument for this loop: the message can no longer restate a body, because it
never sees one. It holds on EVERY rung of this shape and not just the first:
when composing fails, the page is rendered by Python or written out of the
subjects, never by a second model call over the body.

`OPENCLAW_PAGE_SHAPE` is the rollback switch and nothing else. Unset or
`rendered` (the default) composes and sends as above; `legacy` sends the older
model-written page, so a bad shape can be backed out without a deploy. Exactly
ONE model call either way: the two shapes are never both run, because a
comparison nobody reads is not worth doubling the spend for. Every flush logs
an `openclaw_page` line for what the shape decided, plus a second one when
`_unheard_critical` overrules a silence into a page, so what actually reached a
phone sums straight out of the container log instead of being read off a line saying
`silent chars=0`.

The LANGUAGE guard was wired on the legacy path for the reason it is wired on
the brief: that path lands on one pinned recipient's phone and nothing
downstream rendered per language, so a model-written draft can arrive in a
language its reader does not read. On the rendered path there is no draft to check:
`page_render.page_language()` picks the catalogue before a word is written, and
an undeclared reader is a decided case (English) rather than a
default.

Public callables: `flush_pen()` and `start_flusher()`/`stop_flusher()`.

FAILURE POLICY: Tier-2 degrade, never drop, and on the rendered path that rule
is absolute (a guard that can suppress a report is a bug).
Anything that raises while the page is composed (parsing a body, refusing a
selection, filling a template) still ends in a page: first `page_render.floor`,
which never raises and never returns empty, and under that `_plain_page`, the
subjects in plain Python with nothing behind them that can fail. A raise is not
the only way down: a floor whose last line is about itself names no ping in the
batch, and a page that names no ping is not the page for those pings whichever
rung wrote it, so that route reaches `_plain_page` too. Every rung is wrapped, the last one included,
and no rung calls the model a second time; the
legacy page is reachable only through the rollback switch. Budget tripped or
Anthropic faulted is the same floor. Pen
reads/writes are Tier-1 and propagate to the loop, which logs and retries next
tick; pings stay unflushed until a flush truly happened.
"""
from __future__ import annotations

import json as _json
import logging
import os
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from apps.assistant.core import brain as _brain
from apps.assistant.core import claims as _claims
from apps.assistant.core import outbound as _outbound
from apps.assistant.core import page_render as _page_render
from apps.assistant.core import people as _people
from apps.assistant.core import ping_facts as _ping_facts
from apps.assistant.core import quiet_hours as _quiet_hours
from apps.assistant.core import self_context as _self_context
from apps.assistant.core import signal_text as _signal_text
from apps.assistant.core import state as _state
from apps.assistant.shared import local_time as _local_time
from apps.assistant.shared import signal as signal_dispatch

log = logging.getLogger("openclaw.notify_flush")

FLUSH_INTERVAL_SECONDS = 30
# Minimum gap between two pages about an ongoing story. Everything that
# arrives inside the gap is summarised together at the next flush.
STORY_GAP_SECONDS = 300

_SILENT_TOKEN = "SILENT"

# The zone `page_render` renders an observation in, so the evidence can
# carry the same instant in the same zone. Read off `page_render._LOCAL_ZONE`
# rather than restated, because two copies of a timezone drift silently and
# the symptom is a stamp rule flagging every page.
_PAGE_LOCAL_ZONE = _page_render._LOCAL_ZONE

# The rollback switch. `rendered` is the shipping shape and the value
# when the variable is unset; `legacy` puts the model-written page back without
# a deploy. There is deliberately no third value that runs both: a shadow mode
# nobody reads hides real failures, and it doubles the spend to produce a diff.
PAGE_SHAPE_ENV = "OPENCLAW_PAGE_SHAPE"
RENDERED_SHAPE = "rendered"
LEGACY_SHAPE = "legacy"

# How far back a subject's history is read. Same fortnight the recurring filer
# uses, for the same reason: a thing that came back last week is the same story,
# a thing that came back last quarter is a different one. It is therefore also
# the scope of the number on the page: "ping N on this subject" counts the
# pings inside this window, which is the story, not the lifetime of the subject.
HISTORY_WINDOW_DAYS = 14

# How long a delivered critical subject keeps the floor disarmed. Without it,
# the floor asked whether the subject had EVER reached a phone, over a table
# nothing prunes, so one delivery killed the floor for that subject for good.
#
# Twelve hours. Repeats of one critical subject inside the hour are the same
# episode, and the pen exists to collapse them. The same subject the next day
# is a fresh outage and must be said again, which a permanently disarmed floor
# would swallow. Twelve hours sits comfortably over the length of one episode
# and under the gap to the next day, and it means a critical thing that is
# still true after half a day gets said once more.
UNHEARD_WINDOW_HOURS = 12

# `alerts_since` answers at most this many rows. A window that comes back full
# was cut, and it is cut at the OLD end, so every count read off it would
# silently understate. A saturated read is therefore a history that was not
# read, not a smaller history.
ALERT_ROW_LIMIT = 500

# The LEGACY prompt: it asks for prose, and it is reached only under
# `OPENCLAW_PAGE_SHAPE=legacy`. It dies with the flag.
_TASK = """Below are the system pings that piled up since your last look, plus
the last few messages you already sent. You are NOT a relay: collect, think,
decide.

Write ONE short page, or output exactly <note>SILENT</note> when none of it
needs a human.

A page is two things and nothing else: what is broken, and the one thing the
person should check. This is the shape:

  the server disk is almost full, please check df -h / on the server

Rules:
- Name the symptom you actually have. Do NOT name a cause. You ran no checks
  this pass, so "the unit crashed", "the disk filled up" and "this is connected
  to issue N" are guesses, and they have been wrong every time you made them.
- Give the one most useful check: a command, a unit, a page to open.
- Leave out what you cannot see. "I cannot read its systemd state from here"
  and "I cannot run those commands myself" are about you, and the reader
  already knows.
- Do not offer to open an issue, do not ask what they would like you to do, do
  not add next steps. They will tell you.
- One page for the whole batch, never one per ping. If a message of yours
  already said this, say only what CHANGED (started, got worse, recovered);
  when nothing changed, stay SILENT.
- Routine self-healing chatter is noise, judged by your principles: stay
  SILENT.

Plain text, no markdown, no lists, no headers. Wrap the message in <note> and
</note>; only the text inside is sent."""


_SELECT_TASK = """Below are the system pings that piled up since your last
look, one block each, already read out of the ping into fields. Above them are
the last few messages you sent.

You write no prose this pass. The wording of the page is written for you; your
whole job is to call `choose_page` exactly once and pick:

- which ping the page leads with,
- which aspect of that ping is the news, out of the ones its own fields carry,
- which other pings in this batch are worth one line each, and how each relates
  to the lead.

Pick `verdict: "silent"` when this batch is a repeat of something you already
said and nothing about it changed. A batch that says nothing new is the reason
this pen exists, so silence is a good answer far more often than a page.

Do not pick an aspect the ping does not license: "escalation" and "first_seen"
need a history that was actually read, "blocks_deploy" needs the sender to have
said so, "incomplete" needs a body
the sender cut short. "failure" always fits. Anything you pick that the facts
do not carry is refused and the page goes out plain instead.

Call the tool. Do not write anything else."""


def _page_shape() -> str:
    """Which shape composes this page: `rendered` (the default) or `legacy`."""
    return (os.environ.get(PAGE_SHAPE_ENV) or RENDERED_SHAPE).strip().lower()


@dataclass(frozen=True)
class _Decision:
    """What one composing pass decided about a batch.

    `message` is the page, or None for a judged silence. `floor` is the true
    text to send when that silence is overruled by `_unheard_critical`, and it
    is computed by the same shape that judged, so overruling a silence never
    reaches for the other shape's words.
    """

    message: str | None
    floor: str


def _render_pings(pings: list[dict]) -> str:
    """LEGACY ONLY: the whole raw body of every ping, as one user turn.

    This is the line the house rules exists to remove, kept alive only for
    `OPENCLAW_PAGE_SHAPE=legacy`. The rendered path hands the model
    `ping_facts.render`, which carries typed fields and no body. The rendered
    ladder's last rung is `_plain_page`, not this, so the default shape has no body-to-model path left
    in it at all.
    """
    lines = []
    for ping in pings:
        lines.append(
            f"[{ping['received_at'][11:19]}Z {ping['source']}] "
            f"{ping['subject']}\n{ping['body']}"
        )
    return "\n\n".join(lines)


def _fallback_summary(pings: list[dict]) -> str:
    """LEGACY ONLY: raw headlines, the older path's floor. The rendered path
    floors on `page_render.floor`, which speaks in whole sentences."""
    subjects: list[str] = []
    for ping in pings:
        if ping["subject"] not in subjects:
            subjects.append(ping["subject"])
    return (
        f"{len(pings)} system pings, brain unavailable so raw headlines: "
        + "; ".join(subjects[:6])
    )


def _reader_language() -> str | None:
    """LEGACY ONLY: which language the page recipient reads ("nl"/"en"), or
    None when the registry does not say.

    The rendered path asks `page_render.page_language()` instead, which makes
    the same lookup and then DECIDES the undeclared case rather than handing a
    None to a guard. This copy lives on only as the legacy guard's input.
    """
    destination = _outbound.recipient()
    if not destination:
        return None
    person = _people.identify_by_number(destination)
    return _people.language_for(person.name) if person is not None else None


def _marked_must_page(ping: dict) -> bool:
    """Whether this sender said its page cannot wait.

    Read off the pen row's own `facts`, not off the body: this is the one
    marked field that changes what the road DOES rather than what the page
    says, so a body that happens to contain the words cannot set it.

    A bad read answers no. That is the safe direction here even though it
    loses a page: the flag only ever adds sends, so a false no leaves the
    road exactly as it behaved before the flag existed, while a false yes
    would wake somebody at 03:00 on a parse error.
    """
    return _ping_facts.must_page(ping.get("facts"))


def _any_must_page(pings: list[dict]) -> bool:
    """Whether anything in this batch said it cannot wait."""
    return any(_marked_must_page(ping) for ping in pings)


def _split_silenced(pings: list[dict]) -> tuple[list[dict], list[dict]]:
    """The batch, split into what may page and what has already been filed.

    Two different reasons to stay quiet, and keeping them apart matters.

    The assistant filed a backlog card for it and said so once, so it does not raise it
    again; the board carries it from there. That mute lives in
    `filed_observations` and expires.

    Or a human silenced the alert itself, in `suppression`. The Alertmanager
    path honours that; the notify pen must too, or the same silenced failure
    goes on paging.

    A failed read lets the ping through. Paging about something already on the
    board costs attention; swallowing a real page costs more.

    Each silenced ping comes back as a copy carrying `silenced_by`, the card or
    suppression that held it, because an audit row that only counts pings
    cannot say afterwards why a critical was dropped.
    """
    live: list[dict] = []
    silenced: list[dict] = []
    for ping in pings:
        subject = _subject_for_audit(ping["subject"])
        why = None
        try:
            # A filed card holds for every ping on its subject, `must_page` or
            # not. An exemption here would let a filed subject keep paging
            # after its issue body promised the subject had gone quiet. A
            # filed card is matched on the mute key, so the marker the sender
            # wrote this time cannot miss the card filed off a bare spelling.
            # A critical is not exempt either, on purpose: that
            # would re-page every revert ping a filed card holds, the same
            # repeat pages by another flag. The filer already refuses new cards on any key
            # that was ever critical (`recurring_alerts._NEVER_FILE_SEVERITIES`),
            # so only cards filed before that rule can hold one.
            issue = _state.filed_issue_for(subject)
            if issue is not None:
                why = f"filed as #{issue}"
            else:
                suppressed, because = _state.is_suppressed(subject)
                if suppressed:
                    why = f"suppressed: {because or 'no reason given'}"
        except Exception as exc:  # noqa: BLE001, Tier-2: a bad read never drops a page
            log.warning("filed/suppression read failed during flush: %s", exc)
            why = None
        if why is None:
            live.append(ping)
        else:
            silenced.append({**ping, "silenced_by": why})
    return live, silenced


def _held_by(silenced: list[dict]) -> str:
    """The audit reason for a silenced batch: what held it, each cause once."""
    causes = list(dict.fromkeys(str(ping.get("silenced_by") or "") for ping in silenced))
    return f"{len(silenced)} ping(s) held: " + "; ".join(cause for cause in causes if cause)


def _may_be_critical(subject: str) -> bool:
    """Whether this subject could be the first word about an outage.

    Asking `state.severity_of_subject(subject) == "critical"` would answer
    "info" for a subject no sender marked. That would make the pen's whole
    anti-silence mechanism opt-in through an emoji nothing validates, and
    several senders do not write one. An outage-grade subject would read as
    info, so the floor that exists to stop a silenced outage could never fire
    for it.

    So the default for an unmarked subject is NOT the quietest severity, it is
    no answer at all, and no answer arms the floor. The cost of that default is
    bounded and small: the floor only ever overrules a judged SILENCE, and only
    for a subject that has not reached a phone inside `UNHEARD_WINDOW_HOURS`,
    so an unmarked subject can cost at most one page per twelve hours and only
    on a pass where the pen was going to say nothing. The cost of the other
    default is this shape: a stopped pipeline nobody is told about,
    permanently, because the next identical ping is genuinely not news.

    A marker the severity table does not know is treated as unmarked for the
    same reason. The table can fall one sender behind.
    """
    return _state.marked_severity(subject) in (None, "critical")


def _unheard_critical(pings: list[dict], now: datetime) -> str | None:
    """The first subject in this batch that could be critical and that nobody
    has been told about inside `UNHEARD_WINDOW_HOURS`.

    Could be, not is: `_may_be_critical` above says why an unmarked subject
    counts here and a subject its sender called routine does not.

    A batch may be judged noise for good reasons, and usually is: most flushes
    go quiet, and the pen exists to give summaries rather than a page per
    ping. What it may not do is decide that
    the FIRST word about a critical thing is not worth saying.

    Without this, critical flushes such as "verification gate RED",
    "verification gate stuck" or "container deploy failed" can be silenced
    over and over. Every one of those means nothing is shipping, which is a
    fact about the system rather than a judgement about whether it is
    interesting. The deploy log says the alert was sent and Nextcloud Talk has
    it, so the page exists; it is simply never spoken in the one place the
    reader looks.

    Returns None when everything critical here has been said inside the
    window, which is what keeps a repeat quiet. A read that fails lets the
    batch page: saying a thing twice costs attention, swallowing the first word
    about a stopped pipeline costs more.
    """
    since = (now - timedelta(hours=UNHEARD_WINDOW_HOURS)).isoformat()
    for ping in pings:
        subject = ping.get("subject")
        if not _may_be_critical(subject):
            continue
        audit_subject = _subject_for_audit(subject)
        try:
            if _state.pen_subject_delivered(audit_subject, since=since):
                continue
        except Exception as exc:  # noqa: BLE001, Tier-2: a bad read never drops a page
            log.warning("pen delivery read failed during flush: %s", exc)
        return audit_subject
    return None


# The `fingerprint` column's grammar for a pen row. Written here and read back
# here, and it is the only place a flushed batch records how many pings it
# carried, which is what makes a per-subject count of PINGS possible at all.
_FINGERPRINT_PREFIX = "notify-pen:"


def _fingerprint_for(ping_count: int) -> str:
    """The audit fingerprint for a flush that carried `ping_count` pings."""
    return f"{_FINGERPRINT_PREFIX}{ping_count}"


def _pings_in_row(row: dict) -> int | None:
    """How many pings the flush behind this row carried, None when the row does
    not carry that count in the grammar this module writes."""
    text = str(row.get("fingerprint") or "")
    if not text.startswith(_FINGERPRINT_PREFIX):
        return None
    tail = text[len(_FINGERPRINT_PREFIX):]
    return int(tail) if tail.isdigit() else None


def _pen_history_rows(now: datetime) -> tuple[list[dict], bool]:
    """Past pen-flush audit rows inside the history window, and whether the
    window read came back full.

    The pen's own audit is the only per-subject history that exists: one row
    per flushed batch, naming up to four normalised subjects. Alertmanager rows
    are skipped because an alertname is a rule GROUP, not a subject.

    THE SILENCE ROWS ARE DROPPED IN SQL, before the limit. This read asks for
    500 rows over 14 days and keeps the pen-flush ones afterwards, so filtering
    in Python would let every quiet-beat and digest-silence row spend one of
    those 500 before the filter ran. It would not be a silent failure, the saturation flag below is real and
    the caller drops its history index on it, but a per-subject ping count lost
    for bookkeeping rows is lost for nothing.
    """
    since = (now - timedelta(days=HISTORY_WINDOW_DAYS)).isoformat()
    rows = _state.alerts_since(since, limit=ALERT_ROW_LIMIT, exclude_silences=True)
    batched = [row for row in rows if _state.is_batch_row_name(row.get("name"))]
    return batched, len(rows) >= ALERT_ROW_LIMIT


def _history_index(rows: list[dict]) -> dict[str, list[dict]]:
    """Those rows keyed by the normalised subject each one names."""
    index: dict[str, list[dict]] = {}
    for row in rows:
        for subject in _state.subjects_in_row_name(row.get("name")):
            index.setdefault(subject, []).append(row)
    return index


def _batch_occurrences(pings: list[dict]) -> dict[str, int]:
    """How many pings in THIS batch each normalised subject accounts for."""
    counts: dict[str, int] = {}
    for ping in pings:
        subject = _subject_for_audit(ping["subject"])
        counts[subject] = counts.get(subject, 0) + 1
    return counts


def _cleared_the_pen(row: dict) -> bool:
    """Whether the pings behind this flush row actually left the pen.

    This is the difference between an occurrence and an attempt. A page that was decided and not
    delivered leaves its pings in the pen on purpose, so the
    very same pings come back on the next tick and are counted there as this
    batch's own. Counting the failed attempt as well would announce ONE ping,
    enqueued once, as "ping 4 on this subject": three failed sends, one audit
    row each, plus the ping itself.

    A deliberate silence (`batch-noise`, `batch-silenced`) does clear the pen,
    so it is an occurrence like any other.
    """
    if str(row.get("decision") or "") != "batch-page":
        return True
    return bool(row.get("signal_sent_at"))


def _attributable_to(row: dict, subject: str) -> bool:
    """Whether every ping behind this flush row was this subject.

    A row names up to four subjects and carries one ping count for the whole
    batch, so a row naming two subjects proves both arrived and says nothing
    about how the pings split between them. Only a row naming this subject
    ALONE says how many pings of it there were, and only such a row proves the
    page that flush sent named it: the rendered lead sentence always carries
    the lead ping's subject, and in a one-subject batch that is this one.
    """
    return _state.subjects_in_row_name(row.get("name")) == [subject]


def _past_ping_count(rows: list[dict], subject: str) -> int | None:
    """How many pings of `subject` past flushes carried, None when the audit
    cannot say exactly.

    Pings, one unit, all the way through. `seen_count` reaches a template that
    renders a definite ordinal ("Ping 5 on this subject"), so a number that is
    not the true ordinal is a false sentence on a phone, and adding a count of
    FLUSHES to a count of PINGS produces exactly that: three past flushes
    carrying five pings each plus two now is ping 17, not 5.

    Exact or nothing, therefore. A row the pings cannot be pinned on this
    subject by makes the sum unknowable, and an unknowable count is an unread
    history, never a floor dressed up as a census.
    """
    total = 0
    for row in rows:
        if not _cleared_the_pen(row):
            continue
        if not _attributable_to(row, subject):
            return None
        counted = _pings_in_row(row)
        if counted is None:
            return None
        total += counted
    return total


def _delivered_stamp(rows: list[dict], subject: str) -> str | None:
    """When a page that actually named this subject last reached the reader.

    A batch row names up to four subjects, while the page that flush sent leads
    with ONE ping and mentions only the ride-along lines the model picked. A
    subject can therefore ride inside a delivered batch and appear nowhere in
    what the reader saw, and "the last one to reach you at X" about that
    subject is a claim the audit does not support. It is filled only from a
    delivered row naming this subject alone.

    One limit, said out loud: under `OPENCLAW_PAGE_SHAPE=legacy` the page is
    model prose, which is held to no subject, and the row it writes carries no
    mark of the shape that wrote it. A stamp read off a row from a legacy
    window proves the batch reached the reader rather than the sentence.
    """
    stamps = sorted(
        str(row["signal_sent_at"])
        for row in rows
        if row.get("signal_sent_at") and _attributable_to(row, subject)
    )
    return stamps[-1] if stamps else None


def _history_record(
    rows: list[dict], subject: str, in_batch: int
) -> dict[str, Any] | None:
    """One subject's history in the shape `ping_facts` reads, or None when the
    audit cannot answer it exactly.

    `seen_count` counts every ping of this subject the window holds, up to and
    including this batch. One residual, because a batch can carry several pings
    of one subject: the number then belongs to the newest of them while the
    lead line stamps the ping the model led with, which may be an earlier one.

    `first_seen_at` is deliberately never filled. A pen row is stamped when the
    FLUSH ran, not when the ping arrived, and the template that would hold it
    says when the subject was first seen. Two different clocks, and the flush
    clock runs later, so a page filled off it can date the first occurrence of
    a subject AFTER the ping it is paging about. No guard turns one
    clock into the other, so the sentence that needs a sighting time is dropped
    rather than filled off the wrong one.

    `changed_tokens` is empty for a neighbouring reason: nothing on this path
    stores a body between flushes, so what CHANGED between two pings of a
    subject is not knowable here and the renderer drops that sentence too.
    """
    past = _past_ping_count(rows, subject)
    if past is None:
        return None
    return {
        "seen_count": past + in_batch,
        "first_seen_at": None,
        "last_delivered_at": _delivered_stamp(rows, subject),
        "changed_tokens": (),
    }


def _history_source(pings: list[dict], now: datetime) -> _ping_facts.HistorySource:
    """The history lookup `ping_facts.bundle` is handed for this batch.

    Called with the RAW ping subject and normalised here, because
    `_subject_for_audit` is what the audit row grammar and both mutes are
    written against and a second copy of it would drift.

    A subject the audit cannot answer for answers None, which `ping_facts`
    records as "unknown" rather than as a first sighting. Three roads end
    there: no matching row at all (a batch row names at most four of its
    subjects and is cut at 200 characters, so an absence proves nothing), a row
    whose pings cannot be split by subject, and a window read that came back
    full. A missing row is therefore never a first sighting, and "this keeps
    coming back" is only ever said where the rows prove it.

    `first_seen` IS licensed off this source, in one narrow case that is true
    when it happens: a subject whose every row in the window is a page that was
    decided and never delivered. Such a row is not counted (`_cleared_the_pen`),
    and an undelivered page leaves its pings in the pen for the next tick, so the pings the row was written for are the pings in hand
    and this really is the first one. The count says 1 because 1 is the number.

    One read per flush, not one per ping, and it is lazy so a failed read
    reaches `ping_facts.history_for` as the unknown it is.
    """
    occurrences = _batch_occurrences(pings)
    cached: dict[str, dict[str, list[dict]]] = {}

    def history_of(subject: str) -> dict[str, Any] | None:
        if "index" not in cached:
            rows, saturated = _pen_history_rows(now)
            if saturated:
                log.warning(
                    "pen history window came back full at %d rows; no exact count "
                    "is derivable from it, so the history reads unknown",
                    ALERT_ROW_LIMIT,
                )
            cached["index"] = {} if saturated else _history_index(rows)
        normalised = _subject_for_audit(subject)
        rows_for_subject = cached["index"].get(normalised)
        if not rows_for_subject:
            return None
        return _history_record(
            rows_for_subject, normalised, occurrences.get(normalised, 1)
        )

    return history_of


def _no_history(_subject: str) -> Mapping[str, Any] | None:
    """The history source the floor uses: none, read from nowhere.

    The floor runs when something upstream already broke, so it asks no
    database anything. The return type is the `HistorySource` seam's, not
    `None`, because this is one implementation of that seam and the caller may
    not assume the other one is unreachable.
    """
    return None


def _log_page(
    status: str,
    *,
    pings: int,
    selection: _page_render.Selection | None = None,
    chars: int = 0,
) -> None:
    """The line that says what shape decided what, one per decision.

    Greppable as `openclaw_page` and summable straight out of the container log
    (`gates/app` logs bare messages), so the two shapes can be compared on
    real sent pages rather than on what a shape claims it would send. One
    line per flush, except the flush whose judged silence is overruled into a
    page, which logs the silence and then the page it actually sent.
    """
    log.info(
        "openclaw_page shape=%s status=%s pings=%d verdict=%s lead=%s aspect=%s "
        "also=%d chars=%d",
        _page_shape(),
        status,
        pings,
        selection.verdict if selection else "none",
        selection.lead if selection else "none",
        selection.aspect if selection else "none",
        len(selection.also) if selection else 0,
        chars,
    )


def _page_language() -> str:
    """The catalogue this page is written in, and never a raise.

    `page_render.page_language` reads the recipient and the people registry, so
    it faults the same way for every caller. That made it a SHARED dependency
    of the first two rungs below, and one raise inside it would take out the
    selection and the floor together, dropping a whole flush onto the last
    rung for a reason that has nothing to do with either. It is answered here
    once, and an answer that cannot be computed is a decided case rather than a
    fault: English.
    """
    try:
        return _page_render.page_language()
    except Exception as exc:  # noqa: BLE001, Tier-2: a language read never blocks a page
        log.warning("page language read failed (%s); English by ADR-0004", exc)
        return "en"


def _tool_input(response: Any) -> dict[str, Any] | None:
    """The selection the model returned, or None when it returned prose.

    A text-only answer is a normal outcome rather than an error: `brain.run`
    reports it as `finished` with no tool_use block, and the caller floors.
    """
    for block in getattr(response, "content", []):
        if getattr(block, "type", None) != "tool_use":
            continue
        if getattr(block, "name", None) == _page_render.TOOL_NAME:
            return dict(block.input)
    return None


def _selection_decision(pings: list[dict], now: datetime) -> _Decision:
    """One model call over typed facts, validated and rendered into a page.

    The model's only output is the tool input. Nothing it writes as text is
    read, so no path leads from a ping body to Signal.
    """
    facts = _ping_facts.bundle(pings, history_of=_history_source(pings, now))
    language = _page_language()
    composed = _page_render.floor(facts, language=language)
    fallback = _named_page(composed, pings, rung="floor")

    outcome = _brain.run(
        system=_self_context.render("notify", _SELECT_TASK),
        messages=[{"role": "user", "content": _ping_facts.render(facts)}],
        tools=[_page_render.tool_definition(facts)],
        terminal_tools=frozenset({_page_render.TOOL_NAME}),
        cap=1,
    )
    if not outcome.finished:
        log.info("pen flush brain unavailable (%s); floor page", outcome.status)
        _log_page(
            f"{fallback.rung}-{outcome.status}",
            pings=len(facts),
            chars=len(fallback.text),
        )
        return _Decision(message=fallback.text, floor=fallback.text)

    chosen = _tool_input(outcome.response)
    if chosen is None:
        log.info("pen flush returned no selection; floor page")
        _log_page(
            f"{fallback.rung}-no-selection",
            pings=len(facts),
            chars=len(fallback.text),
        )
        return _Decision(message=fallback.text, floor=fallback.text)
    try:
        selection = _page_render.parse_choice(chosen, facts)
    except _page_render.InvalidChoice as exc:
        log.warning("pen flush selection refused (%s); floor page", exc)
        _log_page(
            f"{fallback.rung}-refused", pings=len(facts), chars=len(fallback.text)
        )
        return _Decision(message=fallback.text, floor=fallback.text)

    if selection.verdict == "silent":
        _log_page("silent", pings=len(facts), selection=selection)
        return _Decision(message=None, floor=fallback.text)

    # The rung is the one this pass took, carried as a fact rather than read
    # back out of the text afterwards. `page_render.render` answers with the
    # floor's own words when not one field of the lead fact fills a sentence,
    # and a single-ping batch led as a plain failure renders those same words
    # from a real selection, so the two are one string: comparing them booked
    # the pen's ordinary flush, a lone ping in a calm period, as a floor page
    # and understated the selections the comparison counts. What both
    # routes still have to cross is the door below, which asks the one question
    # about a page that is not a matter of wording.
    page = _named_page(
        _page_render.render(selection, facts, language=language),
        pings,
        rung="selected",
    )
    status = "selected" if page.rung == "selected" else f"{page.rung}-unnamed"
    _log_page(status, pings=len(facts), selection=selection, chars=len(page.text))
    return _Decision(message=page.text, floor=fallback.text)


# The last rung's words. English whatever the reader speaks: reaching this
# line means the machinery that picks a catalogue is itself the thing that
# broke, so it asks nothing and looks nothing up (the house rules decide the
# undeclared reader the same way).
_PLAIN_PAGE_LEAD = "A pen flush could not compose its page."
_PLAIN_PAGE_BLIND = (
    "A pen flush could not compose its page and could not read its own pings."
)


def _plain_page(pings: list[dict]) -> str:
    """The rung under the floor: the subjects, in plain Python.

    No model, no templates, no history, no registry, no database. Every rung
    above this one reaches for something that can raise, so the bottom of the
    ladder has to reach for nothing. It is ugly on purpose; it is what stands
    between a broken renderer and a phone that never rings.
    """
    try:
        subjects: list[str] = []
        for ping in pings:
            # The same spelling every rung above prints, so the bottom rung is
            # not the one place the banner survives.
            subject = _ping_facts.display_subject(ping.get("subject"))
            if subject and subject not in subjects:
                subjects.append(subject)
        if subjects:
            joined = "; ".join(subjects)
            return f"{_PLAIN_PAGE_LEAD} {len(pings)} ping(s) in it, by subject: {joined}."
    except Exception as exc:  # noqa: BLE001, Tier-2: the last rung cannot fail
        log.error("plain pen page raised (%s); sending the bare line", exc)
    return _PLAIN_PAGE_BLIND


# The longest leading run of a subject that every page on this path prints
# whole. Every subject that reaches a reader, in a lead sentence or in the list
# of the others underneath, crosses the one door in `page_render`: a single
# line cut to `VALUE_MAX_CHARS`, a cut one keeping its leading characters and
# an ellipsis. So every spelling of a subject that reaches a page shares a
# leading run longer than this, with room left over for that door to narrow.
_NAMED_SUBJECT_CHARS = 79


def _subject_head(ping: dict) -> str:
    """The leading run of one ping's subject that a page carrying it must show.

    Read through `ping_facts.display_subject`, because that is the spelling a
    page prints: asked against the sender's raw string instead, a subject
    carrying a severity marker or a product banner would match no page at all,
    and the flush would fall to the plain page.
    """
    subject = _ping_facts.display_subject(ping.get("subject"))
    # Whitespace collapsed the way `page_render._page_value` collapses it, for
    # the same reason the strip is read off the same field: a run of two spaces
    # that the page prints as one is a subject this door would look for in a
    # spelling no page ever holds.
    return " ".join(subject.split())[:_NAMED_SUBJECT_CHARS].rstrip()


def _names_the_batch(page: str, pings: list[dict]) -> bool:
    """Whether `page` names a ping of this batch, or the batch has no name to give.

    Not a judgement about the wording: it asks whether the subject one of these
    pings arrived with is in the text, which is a comparison against the rows in
    hand rather than a reading of the sentence.

    A batch whose every subject is empty has nothing to be named by, and a page
    about it is as good as it will ever be, so that case answers yes. It is the
    only case in which a page naming no ping is the page for these pings.

    Where it is wrong it is wrong toward the plain page. A spelling of a subject
    this misses costs the reader the prettier page and never a ping, because the
    rung it falls to names every subject in the batch.
    """
    heads = [head for head in (_subject_head(ping) for ping in pings) if head]
    if not heads:
        return True
    return any(head in page for head in heads)


@dataclass(frozen=True)
class _Page:
    """The text a flush sends, and which rung of the ladder wrote it.

    `rung` rides along so the `openclaw_page` line can say which one spoke.
    A status naming a rung that did not write the text is the measurement
    telling the comparison about a page nobody was sent.
    """

    text: str
    rung: str


def _named_page(text: str, pings: list[dict], *, rung: str) -> _Page:
    """`text` when it names a ping of this batch, the plain page when it does not.

    Every page the rendered shape sends crosses this door, the selected one as
    well as the floor, because the reason is the same on both routes: the
    caller sends what it gets, audits it as the page for those pings and clears
    the pen on it.

    `page_render.floor` is written never to raise, so a failure inside it comes
    back as a sentence about itself instead: "A pen flush ran and this page
    could not be assembled" names none of the pings it was called for, so a
    batch holding a readable gate verdict and a readable unit failure would
    leave the pen on a page naming neither. A selected page arrives at the
    same place by another route: a lead sentence with no subject slot in it
    renders a page about a host and a unit and names no ping of the batch. That
    one is not live, because the gate refuses a ping without a subject, but the
    refusal is in another module and this is the page's own door.

    `_plain_page` reaches for nothing at all and names the subjects in hand, so
    it is the answer whenever the page above it named none of them. The one
    batch that cannot be named is the one carrying no subject at all, and
    `_names_the_batch` answers yes for it. Losing a ping is worse than sending
    an ugly page twice.
    """
    if _names_the_batch(text, pings):
        return _Page(text=text, rung=rung)
    log.warning(
        "pen %s page named no ping of this batch; sending the plain page so "
        "the pen is cleared by a page that named them",
        rung,
    )
    return _Page(text=_plain_page(pings), rung="plain")


def _selected_page(pings: list[dict], now: datetime) -> _Decision:
    """The rendered shape, which cannot fail its way into silence.

    Three rungs, in order, because the house rules says a guard that can
    suppress a report is a bug and that binds this rewrite harder than anything
    it replaces: the selection, then `page_render.floor`, then `_plain_page`.

    Every rung is wrapped, the last one included. Unwrapped, the way that
    fails is not a worse page but no page at all: a raise in a dependency the
    first two rungs share goes out of `_compose`, out of `flush_pen` and into
    the loop's blanket except. Nothing is sent, the pings stay in the pen,
    and every retry hits the same raise, which is permanent silence produced by
    the guard that exists to prevent it. The shared dependency is the language
    read, which `_page_language` now answers instead of raising; `_plain_page`
    is the rung that needs nothing at all and cannot raise either.

    A raise is not the only way down to it, and treating it as the only way
    would leave the bottom rung unreachable in practice. `page_render.floor` is
    written never to raise, so a floor that could not assemble anything returns
    a line about itself rather than failing, and this took that line for a
    delivered page. `_named_page` is the second door: a page naming no ping of
    this batch is not the page for it, whichever rung wrote it, and the plain
    page underneath names them.

    The last rung is not `_legacy_page`, which puts the whole raw body into
    a prompt and would give the shipping shape a body-to-model-to-wire path in
    its last resort. No rung here calls the model twice, and the legacy page is reachable
    only through `OPENCLAW_PAGE_SHAPE=legacy`.
    """
    try:
        return _selection_decision(pings, now)
    except Exception as exc:  # noqa: BLE001, Tier-2: a raise still sends a page
        log.error("pen page selection raised (%s); rendering the floor", exc)
    try:
        facts = _ping_facts.bundle(pings, history_of=_no_history)
        composed = _page_render.floor(facts, language=_page_language())
        fallback = _named_page(composed, pings, rung="floor")
    except Exception as exc:  # noqa: BLE001, Tier-2: the last rung is plain text
        log.error("pen page floor raised (%s); sending the plain page", exc)
        fallback = _Page(text=_plain_page(pings), rung="plain")
    _log_page(f"{fallback.rung}-raised", pings=len(pings), chars=len(fallback.text))
    return _Decision(message=fallback.text, floor=fallback.text)


def _legacy_page(pings: list[dict]) -> _Decision:
    """The model-written page, reached only under `OPENCLAW_PAGE_SHAPE=legacy`.
    One model call, guards on the draft, raw headlines when there is nothing
    left."""
    nudged = {"done": False}

    def _on_text(response) -> str | None:
        """Did-you-LOOK gate: this path has no checks behind it. No tools
        this call, so a page stating a bare cause is diagnosing blind: nudge
        once; the strip below is the last resort. A recommended repair is
        gated apart from the cause that motivates it: this
        call checked nothing, so it may name what to LOOK at and not what to
        change. The same single nudge also carries the language check:
        every batch lands on the same phone and nothing downstream renders per
        language."""
        if nudged["done"]:
            return None
        note = _signal_text.extract_note(_signal_text.text_of(response))
        if _signal_text.is_sentinel(note, _SILENT_TOKEN):
            return None
        nudge = (
            _claims.unbacked_causal_page(note)
            or _claims.unbacked_remedy(note)
            or _claims.wrong_language(note, _reader_language())
        )
        if nudge:
            log.warning("pen flush tripped a guard; nudging")
            nudged["done"] = True
        return nudge

    system = _self_context.render("notify", _TASK)
    outcome = _brain.run(
        system=system,
        messages=[{"role": "user", "content": _render_pings(pings)}],
        tools=[],
        cap=2,
        on_text=_on_text,
    )
    floor_text = _fallback_summary(pings)
    if not outcome.finished:
        # Never drop a batch on a tripped budget or a brain outage (Tier-2):
        # send the raw headline summary instead.
        log.info("pen flush brain unavailable (%s); raw fallback", outcome.status)
        _log_page(f"legacy-{outcome.status}", pings=len(pings), chars=len(floor_text))
        return _Decision(message=floor_text, floor=floor_text)

    note = _signal_text.extract_note(_signal_text.text_of(outcome.response))
    if _signal_text.is_sentinel(note, _SILENT_TOKEN):
        _log_page("legacy-silent", pings=len(pings))
        return _Decision(message=None, floor=floor_text)

    message = _signal_text.strip_markdown(note) or floor_text
    if _claims.unbacked_causal_page(message):
        # Nudged and still diagnosing: the page goes out symptom-only, never
        # blocked.
        message = _claims.strip_causal_sentences(message) or floor_text
    if _claims.unbacked_remedy(message):
        # Nudged and still handing over a repair this call could not justify:
        # the instruction goes, the symptom stays.
        message = _claims.strip_unbacked_remedy(message) or floor_text
    _log_page("legacy-page", pings=len(pings), chars=len(message))
    return _Decision(message=message, floor=floor_text)


def _compose(pings: list[dict], now: datetime) -> _Decision:
    """The page for this batch, from the shape that is deployed."""
    if _page_shape() == LEGACY_SHAPE:
        return _legacy_page(pings)
    return _selected_page(pings, now)


# The fields of a pen row that a renderer prints as ONE line: `ping_facts.render`
# writes each into a line of a block-structured prompt, and `_plain_page` writes
# the subject into a sentence. The body is deliberately not among them. Its line
# structure is what `ping_facts.parse` reads, so flattening it would break the
# parse; what that parser lifts out of a body, and how, is its own business and
# not restated here. The legacy prompt hands over raw bodies whole, which is that
# shape's own property and dies with the flag.
_LINE_FIELDS = ("subject", "source", "received_at")


def _one_line(value: Any) -> Any:
    """`value` with every line break in it turned into a space; anything that is
    not text comes back untouched, having no line to break."""
    if not isinstance(value, str):
        return value
    return " ".join(value.splitlines())


def _flattened(pings: list[dict]) -> list[dict]:
    """The batch with every field that is printed as one line held to one line.

    A pen row is written by whoever POSTed `/webhook/notify`, and its subject
    travels from there into a prompt whose grammar IS its line structure: one
    block per ping, a header line carrying that ping's id, kind and severity,
    and one indented field line under it. A newline inside a subject closes the
    line the renderer opened and starts lines of its own, so a sender can write
    a whole second ping that way, forged id and kind and history line included,
    underneath a preamble telling the model every line it is reading was put
    there by code out of a real ping. The tool's id enum keeps a forged ping out
    of the lead, so it cannot become the page's subject, but it still reaches
    the page-or-silent verdict and the aspect, and it makes the preamble false.

    Flattened at the seam where a stored row becomes this module's batch, so the
    prompt, the pages and the audit all read the same text.
    """
    flat: list[dict] = []
    for ping in pings:
        row = dict(ping)
        for name in _LINE_FIELDS:
            if name in row:
                row[name] = _one_line(row[name])
        flat.append(row)
    return flat


def _morning_gate_shut(now: datetime) -> bool:
    """Is the morning still holding? Asked of `page_hold`, never re-derived.

    Imported inside the function on purpose: `page_hold` imports
    `STORY_GAP_SECONDS` from this module at import time, so a module-level
    import here closes the cycle. Same reason the flusher loop below reaches
    for it the same way.

    Tier-2: a fault answers "not holding", so a broken gate can only make this
    road send as it always did, never make it go quiet.
    """
    try:
        from apps.assistant.core import page_hold

        return page_hold.morning_gate_shut(now)
    except Exception as exc:  # noqa: BLE001 - Tier-2: never hold a page on a fault
        log.error("morning gate unreadable (%s); sending as usual", exc)
        return False


def _hold_for_the_brief(message: str, pings: list[dict]) -> None:
    """Queue this batch's page so the morning brief carries it.

    Its subject is the batch's own subjects, each once, because that is what
    the brief lists and what `page_hold` checks the delivered brief named
    before it counts the page as carried. "the night" named nothing a
    brief could repeat, so every pen page would have been sent twice.
    """
    from apps.assistant.core import page_hold

    subjects = dict.fromkeys(_subject_head(ping) for ping in pings)
    subject = page_hold.SUBJECT_JOIN.join(head for head in subjects if head)
    # A list too long for the subject column would be cut mid-subject, and a
    # cut subject can be "named" by any text; "the night" is never named, so
    # that page always leaves on its own as well.
    if not subject or len(subject) > page_hold.SUBJECT_CHARS:
        subject = "the night"
    page_hold.hold_beat(message, subject=subject, road="pen")


def flush_pen(now: datetime | None = None) -> str | None:
    """One flush pass: decide whether it is time, then turn the batch into one
    message (sent + remembered) or silence. Returns the sent text, None when
    nothing was flushed or the batch was silent."""
    if now is None:
        now = datetime.now(timezone.utc)

    pings = _flattened(_state.unflushed_pings())
    if not pings:
        return None

    # The pacing clock is what the pen SAID, not what it cleared. Reading
    # MAX(flushed_at) off the pen would make every silence look like a page
    # that had just gone out; most flushes send nothing, so the pen would sit
    # in a story gap of its own making and each real page would wait behind
    # one. Reading the clock before the silenced pings are cleared only keeps
    # the CURRENT pass honest; a gap opened by the previous pass is already
    # there and no ordering here can close it. `alerts.last_pen_page_at` answers the question the clock is actually
    # asking. The window is the story gap itself, because anything older than
    # the gap has already passed it.
    last_page = _state.last_pen_page_at(
        since=(now - timedelta(seconds=STORY_GAP_SECONDS)).isoformat()
    )

    pings, silenced = _split_silenced(pings)
    if silenced:
        # Cleared from the pen without a page. The subject already has a card
        # on the board, which is where a thing that keeps coming back belongs
        #: the audit row still records that it arrived.
        _state.mark_flushed([ping["id"] for ping in silenced])
        _audit(silenced, sent=False, reason="batch-silenced", why=_held_by(silenced))
    if not pings:
        return None

    if _quiet_hours.quiet_now(now) and not _any_must_page(pings):
        # HELD, NOT DROPPED. The pings stay unflushed and go out as one page
        # when the window ends at 07:30 local.
        #
        # `quiet_hours` was written for patrol and says in its own docstring
        # that the paging path never consults it, on the reasoning that a page
        # is urgent by definition. That reasoning does not hold on THIS road.
        # A deploy gate going red usually heals without anybody touching it,
        # because a gate refusing to ship IS the safety mechanism working, and
        # a secret-scan finding is about a commit already pushed. Neither needs
        # a person before morning; paging them only wakes a person up.
        #
        # This road carries deploy pings, systemd unit failures and probe
        # results, and none of them is a thing a person can act on at 02:00
        # that they could not act on at 07:30.
        #
        # THE ROADS THAT CAN STILL WAKE THE OWNER: the two deadman switches page
        # signal-cli direct and never enter the pen. An Alertmanager critical
        # does too: triage's draft is queued in `page_hold`, which
        # releases a critical at once through quiet hours
        # and the morning gate and holds only warnings and info.
        #
        # There is now a third way through, and it is narrower than a direct
        # path: `must_page`, which
        # a sender sets per page and which skips this hold while keeping the
        # rest of the road, so what arrives is still the assistant's sentence about what
        # the thing was rather than the sender's raw text. The auto-eject is the
        # one sender that sets it: a commit being reverted off
        # main is somebody's work being handed back, they are usually still at
        # the keyboard, and a page held until morning goes unseen. Do not
        # reach for it because a sender feels important. The test is whether the
        # reader loses something by hearing it at 07:30, and for the deploy
        # pings, unit failures and probes above, they do not.
        log.info("quiet hours: holding %d ping(s) until the window ends",
                 len(pings))
        return None

    if last_page is not None:
        gap = now - datetime.fromisoformat(last_page)
        oldest = now - datetime.fromisoformat(pings[0]["received_at"])
        # Inside the story gap we keep collecting, unless the oldest ping
        # has itself been waiting a full gap (flusher was down; catch up).
        if gap < timedelta(seconds=STORY_GAP_SECONDS) and oldest < timedelta(
            seconds=STORY_GAP_SECONDS
        ):
            return None

    ping_ids = [ping["id"] for ping in pings]

    decided = _compose(pings, now)
    if decided.message is None:
        unheard = _unheard_critical(pings, now)
        if unheard is None and _any_must_page(pings):
            # Same overrule as the floor below, on a different trigger. The
            # floor asks whether a critical subject has gone unheard for twelve
            # hours; this asks nothing, because the sender already answered.
            unheard = "a sender marked this page as one that cannot wait"
        if unheard is None:
            _state.mark_flushed(ping_ids)
            _audit(pings, sent=False, reason="batch-noise")
            return None
        # First word about something critical, and the verdict was silence.
        # The floor does not argue with the judgement, it only refuses to let
        # it be the reason nobody ever hears. Same shape as the triage silence
        # floor, and the same reason: a wrong silence here is permanent,
        # because the next identical ping is genuinely not news.
        log.warning("pen flush said SILENT on an unheard critical (%s); raising it",
                    unheard)
        message = decided.floor
        # The shape already logged this flush as `silent` with no characters,
        # because the overrule happens here and not inside it. Left at that,
        # the one grammar the comparison sums says nothing went out on the
        # flush that sent a critical page, which is the measurement making the
        # same mistake the pages were making.
        _log_page("silent-overruled", pings=len(pings), chars=len(message))
    else:
        message = decided.message

    # In the morning window the page is QUEUED, not sent, so it leaves inside
    # the brief instead of half an hour ahead of it. Everywhere else
    # this road is unchanged and still sends on its own pacing: the pen holds
    # unread PINGS overnight, which is cheap, and this is the one stretch of
    # clock where holding the written page as well buys something, because the
    # thing it would be waiting for is minutes away and is the report this page
    # belongs in. Outside that window a held page would be a second brake with
    # a second story gap in front of an already-paced road.
    if _morning_gate_shut(now):
        _hold_for_the_brief(message, pings)
        # Audited as a page and the pings cleared, both deliberately. It IS the
        # page for this batch, so composing a second one thirty seconds later
        # would put the same night out twice; `alerts.last_pen_page_at`, which
        # is this road's own pacing clock, has to see it for that reason.
        _audit(pings, sent=False, reason="batch-queued")
        _state.mark_flushed(ping_ids)
        _log_page("queued-for-brief", pings=len(pings), chars=len(message))
        return message

    # Empty subject: openclaw's own voice carries no banner line. On
    # the local clock before the send, so what is remembered below is the
    # text the owner read.
    message = _local_time.in_local_time(message, now)
    delivered = signal_dispatch.send(subject="", body=message)
    _audit(pings, sent=delivered, reason="batch-page")
    if not delivered:
        # Leave the pings in the pen so the batch is retried, rather than
        # clearing them and losing the page. If the assistant is mute for a
        # night, every batch flushed in that window would otherwise be dropped
        # silently. The story gap bounds how
        # often this retries; the deliberate-silence path above still clears,
        # because choosing not to send is not a failed send.
        log.warning("pen flush not delivered; keeping %d ping(s) for retry", len(ping_ids))
        return None
    _outbound.remember_sent("", message, loop="pen")
    # And beside it, what the pen actually READ to write that page.
    # The rows themselves, not `ping_facts.bundle`: the bundle is a typed
    # parse of exactly these rows, so recording the rows loses nothing a
    # checker needs and costs no second history read. It is also the better
    # evidence for the one thing a checker does with it, matching a number or a
    # stamp in the page against something a reading contains, because the page
    # is rendered from these bodies.
    _outbound.remember_readings("pen", message, _pen_readings(pings))
    # Cleared on a page that named these pings. Which page that is was settled
    # while it was composed (`_named_page`), on the selected route and the
    # floor route both, because the rendered shape is the only one that can
    # answer the question: under `OPENCLAW_PAGE_SHAPE=legacy` the page is model
    # prose held to no subject.
    _state.mark_flushed(ping_ids)
    return message


def _both_renderings(received_at: str) -> str:
    """One recorded instant written every way the page can write it.

    `page_render` prints an observation as LOCAL time with the UTC time beside
    it ("At 2026-01-15 09:30 local (08:30 UTC)"), and the pen stores
    `received_at` in UTC. So evidence carrying only the stored string leaves the
    local half of every page looking unread, and a textual stamp rule flags the
    time on every pen page ever sent.

    BOTH ZONES. Emitting the stored string and its UTC form would, on a
    UTC-stored row, give the same string twice and fix nothing, while a
    fixture carrying a local offset would make it look fixed.

    Returns the input unchanged when it will not parse: an unparseable stamp is
    still the honest record of what the row held.
    """
    try:
        moment = datetime.fromisoformat(received_at)
    except ValueError:
        return received_at
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (
        f"{received_at} "
        f"({moment.astimezone(timezone.utc).isoformat()} UTC, "
        f"{moment.astimezone(ZoneInfo(_PAGE_LOCAL_ZONE)).isoformat()} local)"
    )


def _pen_readings(pings: list[dict]) -> list[_outbound.Reading]:
    """One reading per pen row in the batch: what the flush had in front of it.

    `outcome` IS THE WORD THE TOOL LAYER USES FOR WHAT CAME BACK. Putting the
    sender's severity marker there instead would read fine and silently empty
    the evidence trail the claim audit exists to leave. `claim_audit.check` filters readings on `outcome == "ok"`
    in three places: `evidence_text` builds the block the rules match words
    against, and the `successful` and `board` counters feed
    `unbacked_causal_claim`, `unbacked_board_statement` and
    `fabricated_issue_numbers`. A reading stamped "critical" or "unmarked"
    matches none of them, so every pen message would reach the checker with an
    empty evidence block and a read count of zero: the checker-only stamp rule
    would answer False by construction and the whole-message rules would judge
    against nothing. Only the text-only rules, which need no evidence, could
    still fire on a pen page.

    (The stamp rule is deliberately not named here: it must not appear in a
    loop module, because it is checker-only and would fire
    on legitimate arithmetic in a draft. The guard cannot tell a mention from a
    call, and its teeth are worth more than this sentence's precision.)

    The severity is a real fact and it is not lost: it rides in `arguments`
    beside the source, which no rule filters on. "The sender called this
    routine" and "nobody said anything" stay apart, which is what
    `state.marked_severity` returning None is for.
    """
    readings = []
    for ping in pings:
        body = str(ping.get("body") or "")
        subject = str(ping.get("subject") or "")
        readings.append(
            _outbound.Reading(
                tool="notify_pen",
                arguments=_json.dumps(
                    {
                        "source": str(ping.get("source", "")),
                        "severity": _state.marked_severity(subject) or "unmarked",
                    },
                    sort_keys=True,
                ),
                outcome=_outbound.READING_OK,
                digest=_state.message_evidence.digest_of(body),
                chars=len(body),
                # The observed time is IN the excerpt, not only in `at`, and it
                # is there in BOTH renderings of the instant. The excerpt is
                # the only field `claim_audit.check.evidence_text`
                # concatenates, and `page_render` prints the ping's own
                # observation time as local time AND as UTC ("At 2026-01-15
                # 12:00 local (11:00 UTC)"). With only the stored ISO
                # string here, the UTC half of every rendered page is a
                # timestamp appearing in no evidence, so the stamp rule flags
                # every pen page ever sent. That is a whole false-positive
                # class, and it would make the weekly report unreadable.
                #
                # The flush genuinely had this instant in front of it, so the
                # answer is to record it rather than to except the rule. Both
                # forms, because the same moment written two ways is one fact
                # and a textual rule cannot know that.
                excerpt=(
                    subject
                    + "\n"
                    + body
                    + "\nobserved at "
                    + _both_renderings(str(ping.get("received_at") or ""))
                ),
                at=str(ping.get("received_at") or ""),
            )
        )
    return readings


# The product banner some senders put in front of the subject is read off in
# `ping_facts.split_subject`. It carries nothing into the audit, and left in it
# would eat a short budget: "❌ [the project] systemd unit failed: " is 36
# characters on its own, leaving little of the unit name.
#
# The SEVERITY MARKER in front of it is kept HERE, deliberately, which is why
# the split hands it back rather than dropping it. It is one or two characters
# and it is the only per-subject severity anyone records: a batch row holds up
# to four subjects and one severity column, so stripping the markers would leave the
# recurring filer unable to tell which ping in a batch was the serious one, and
# blacklisting every subject on any row that held a critical ping instead
# would make an unrelated subject in the same batch unfileable. Keep the marker
# and the attribution is exact. A page shows neither
# (`ping_facts.display_subject`); an audit row is not a page.
#
# Long enough that a real subject survives whole; the `name` column is capped
# at 200 below, which bounds the row however many pings land in one batch.
_SUBJECT_CHARS = 90


def _batch_severity(pings: list[dict]) -> str:
    """The loudest severity marked on any ping in the batch.

    Senders mark their subjects, and throwing that away would stamp every
    audit row `severity="info"`, making the recurring filer's "never mute
    anything critical" rule dead code on this path. The parser lives on the alerts
    adapter, next to the rest of that table's grammar.
    """
    worst = "info"
    for ping in pings:
        worst = _state.louder(worst, _state.severity_of_subject(ping.get("subject")))
    return worst


def _subject_for_audit(subject: str) -> str:
    """A ping subject as the audit should hold it: product banner off, severity
    marker kept, and cut only where a subject is genuinely long rather than
    merely prefixed.

    This string is the mute key and the history key, so what it holds may not
    move: `ping_facts.split_subject` does the reading, and this puts the marker
    back in front of it exactly as it always did.
    """
    marker, text = _ping_facts.split_subject(subject)
    return ((marker + " " if marker else "") + text)[:_SUBJECT_CHARS]


def _audit(pings: list[dict], *, sent: bool, reason: str, why: str = "") -> None:
    """One audit row per flushed batch (not per ping). `why` replaces the
    count in the reason column when the caller knows the cause."""
    subjects = sorted({_subject_for_audit(p["subject"]) for p in pings})[:4]
    _state.record_alert(
        fingerprint=_fingerprint_for(len(pings)),
        name=_state.batch_row_name(len(pings), subjects),
        severity=_batch_severity(pings),
        status="firing",
        decision=reason,
        reason=why or f"{len(pings)} pings in one flush",
        signal_sent=sent,
        # A page decided and not delivered is exactly what a dead letter is.
        # Hardcoded False, `monitor.dead_letters.check` would be structurally
        # blind to every page this flusher failed to send. A deliberate silence is not a dead
        # letter, which is why the reason matters here.
        dead_letter=(reason == "batch-page" and not sent),
    )


_start_lock = threading.Lock()
_thread: threading.Thread | None = None
_stop = threading.Event()


def start_flusher() -> None:
    """Start the pen-flush loop once (idempotent; same double-startup
    guard as the monitor runner)."""
    global _thread
    with _start_lock:
        if _thread is not None and _thread.is_alive():
            return
        _stop.clear()
        _thread = threading.Thread(
            target=_loop, name="openclaw-notify-flush", daemon=True
        )
        _thread.start()
        log.info("notify pen flusher started (interval %ds)", FLUSH_INTERVAL_SECONDS)


def stop_flusher() -> None:
    """Signal the loop to stop after its current sleep (test hook)."""
    _stop.set()


def _loop() -> None:
    while not _stop.is_set():
        try:
            # Attacker-alerting first: it may enqueue a security ping,
            # which this same flush then collects and sends.
            from apps.assistant.core import security_sweep
            security_sweep.sweep_security()
        except Exception as exc:  # noqa: BLE001, Tier-2: security sweep must not kill the flusher
            log.error("security sweep raised (swallowed): %s", exc)
        try:
            flush_pen()
        except Exception as exc:  # noqa: BLE001, Tier-2: the flusher must survive one bad pass
            log.error("pen flush raised (swallowed): %s", exc)
        try:
            # The shared brake, after the pen has had its pass, so a page the
            # pen just queued can leave in the same message as a triage draft
            # rather than one tick behind it.
            from apps.assistant.core import page_hold
            page_hold.release()
        except Exception as exc:  # noqa: BLE001, Tier-2: one bad pass must not stop the loop
            log.error("page release raised (swallowed): %s", exc)
        _stop.wait(FLUSH_INTERVAL_SECONDS)
