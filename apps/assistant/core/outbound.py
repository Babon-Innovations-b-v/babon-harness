"""Outbound-into-memory seam, remember what openclaw sent.

Everything openclaw pushes to a human (triage pages, processed notifies,
monitor digests, the patrol line) would otherwise
vanish the moment it was sent: the chat brain would have no record of it, so
an hour later openclaw could deny knowing its own reports. `remember_sent`
appends the delivered message to the recipient's `chat_turns` history as
an `assistant` turn. The in-container chat loop that replayed it is gone
(the gateway answers chat now), so what reads it today is
`recent_sent()` below and the `my_actions` door tool, which is how the
gateway's chat session learns what the assistant said outside it.

The recipient key matches the chat sender key: `SIGNAL_RECIPIENT`, else
the first `SIGNAL_ALLOWLIST` entry, normalised the same way inbound
senders are (`gates.e164`, a pure transform, safe to reach across the
layer for). No destination configured means nothing to remember.

`remember_readings(loop, text, readings)` is the same idea one layer
deeper: it stores the released message together with
what the loop READ to write it, in one `message_evidence` row. Every
message is durable but a reading on its own is not, so without this a
sentence like "stuck since 09:00 UTC" could not be checked against the
reading behind it even minutes later. `Reading` is that call's signature type and rides
with it.

`remember_door_reading(tool, arguments, outcome, result_text)` and
`door_readings(window_seconds)` are the same record for the MCP door: every answer the door hands the gateway is kept for a while, so
`message_teammate` can refuse a message citing an issue no tool returned.
The gateway sends no session key to the door, so these readings are
UNATTRIBUTED: one window shared by every gateway session, not this run's.

`record_quiet(beat, reason)` is the mirror of `record_delivery` and it
arrived last: one row saying a beat had its chance
and took it to stay silent, with the reason from a closed vocabulary.
Everything above records what was said; this records what was not, which
is the half no guard in this system has ever been able to see.

Public callables: `remember_sent(subject, body)`, `recipient()` (the
resolved page destination) and `recent_sent()`, the last few messages
openclaw sent that person, rendered as a don't-repeat-yourself prompt
block. The notify-pen flusher and the alert-triage loop both paste it
in, so a re-delivered alert or a rumbling story gets "what changed",
not the same page again.

FAILURE POLICY: Tier-2, defended swallow, the message already left the
building; failing the caller now would make gateway callers re-send
(duplicate pages) without undoing anything. A failed memory write is
logged, never raised.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from apps.assistant.core import state
from apps.assistant.core.state import message_evidence as _message_evidence
from apps.assistant.gates.e164 import normalize_number

log = logging.getLogger("openclaw.outbound")


def recipient() -> str | None:
    """The E.164 the pages go to, same resolution as the send path
    (`SIGNAL_RECIPIENT`, else the first `SIGNAL_ALLOWLIST` entry), same
    normalisation as inbound chat senders, so the history keys line up."""
    explicit = os.environ.get("SIGNAL_RECIPIENT", "").strip()
    if explicit:
        return normalize_number(explicit)
    allowlist = os.environ.get("SIGNAL_ALLOWLIST", "")
    for entry in allowlist.split(","):
        if entry.strip():
            return normalize_number(entry)
    return None


def recent_sent(max_messages: int = 4) -> str:
    """The last few messages openclaw sent the page recipient, as a
    DON'T-REPEAT-YOURSELF prompt block ('' when none/unreadable:
    Tier-2: context, not correctness)."""
    destination = recipient()
    if destination is None:
        return ""
    try:
        turns = state.recent_chat_turns(destination, max_turns=8)
    except Exception as exc:  # noqa: BLE001, Tier-2: context, not correctness
        log.warning("recent-outbound read failed: %s", exc)
        return ""
    texts = [t["text"] for t in turns if t["role"] == "assistant"]
    waiting = _waiting_to_go(max_messages)
    if not texts and not waiting:
        return ""
    block = (
        "WHAT YOU ALREADY TOLD THEM RECENTLY, if this alert or story is "
        "already covered here and nothing material changed, stay SILENT; "
        "when something DID change, say only what changed:\n"
        + "\n---\n".join(texts[-max_messages:])
    )
    return block + waiting


def _waiting_to_go(max_messages: int) -> str:
    """The pages already written and queued but not yet sent.

    THIS IS WHAT KEEPS THE HOLD FROM BACKFIRING. A model loop decides whether to
    speak by reading what the assistant already said, and that read goes through
    `chat_turns`, which `remember_sent` only writes after a successful send.
    Once `page_hold` holds a page overnight it is not there, so triage stops
    seeing "already paged" and stops silencing the follow-ups it would otherwise
    have silenced. Most silences on that road cite a page a hold would have
    prevented, so without this block the morning release would carry several
    times as many drafts.

    Said as plainly as the block above it, because the instruction is different:
    the reader has ALREADY been told this, just not yet out loud, so a repeat is
    still a repeat and saying it again only makes the morning longer.
    """
    from apps.assistant.core import page_hold

    try:
        held = page_hold.held_recently(max_messages)
    except Exception as exc:  # noqa: BLE001, Tier-2: context, not correctness
        log.warning("held-page read failed: %s", exc)
        return ""
    if not held:
        return ""
    return (
        "\n\nALREADY WRITTEN AND WAITING TO GO OUT, held for the quiet window "
        "and leaving in the next message. Treat these exactly like the ones "
        "above: if your alert is covered here, stay SILENT.\n"
        + "\n---\n".join(row["text"] for row in held)
    )


def remember_sent(
    subject: str, body: str, loop: str = "page", worklist_items: tuple[int, ...] = ()
) -> None:
    """Record one delivered outbound message in the recipient's chat
    history. Call it AFTER a successful send, an undelivered message was
    never said, so it is not remembered. `loop` names the road it left by,
    which is what the chat relay reads, and `worklist_items` the
    worklist items the message is about, which the relay names to the chat."""
    destination = recipient()
    if destination is None:
        return
    text = f"[{subject}] {body}" if subject else body
    try:
        state.append_chat_turn(
            destination, "assistant", text, loop=loop, worklist_items=worklist_items
        )
    except Exception as exc:  # noqa: BLE001, Tier-2: the send already happened; never re-fail the caller
        log.error("outbound memory write failed (swallowed): %s", exc)


# The `outcome` that means a read actually returned something. It is the word
# `core.chat` and `core.patrol` already write when a tool result was neither
# UNAVAILABLE nor FAILED, and it is named here because it is a CONTRACT rather
# than a convention: `claim_audit.check` filters readings on it in three places,
# so a writer that puts some other word in this field does not merely label a
# row oddly, it removes that row from every rule that reads evidence. Storing
# a sender's severity marker here, for example, would empty the evidence block
# of every message it wrote.
READING_OK = "ok"


@dataclass(frozen=True)
class Reading:
    """One thing a loop read while it was composing a message.

    The `digest` is the sha256 of the WHOLE result and the `excerpt` is the
    bounded part a checker matches words against, so a truncated excerpt is
    still tied to exact bytes. `outcome` is the tool layer's own word for what
    came back (ok, failed, unavailable), recorded as data rather than
    re-derived later from a string prefix.
    """

    tool: str
    arguments: str
    outcome: str
    digest: str
    chars: int
    excerpt: str
    at: str

    @classmethod
    def of(
        cls,
        tool: str,
        arguments: Mapping[str, Any] | None,
        outcome: str,
        result_text: str,
    ) -> "Reading":
        """One reading built from a tool call and what it returned."""
        return cls(
            tool=tool,
            arguments=json.dumps(dict(arguments or {}), sort_keys=True, default=str),
            outcome=outcome,
            digest=_message_evidence.digest_of(result_text),
            chars=len(result_text),
            excerpt=result_text,
            at=state.utcnow_iso(),
        )


def remember_readings(
    loop: str,
    text: str,
    readings: Sequence[Reading],
    recipient: str = "",
) -> None:
    """Record one released message together with what was read behind it.

    Same seam and same reasoning as `remember_sent` above: this is bookkeeping
    ABOUT a message that has already been composed and released, so a failed
    write is logged and never raised. Failing the caller here would cost a real
    message to save a record of it.

    WHAT THIS RECORDS IS WHAT WAS RELEASED, not what Signal accepted. Three of
    the four loops hand their finished text to the gate, which does the sending
    (`gates/app.py`), and the pen hands its own to `signal_dispatch.send`.
    Whether a message ARRIVED is a separate audit, written by `record_delivery`
    below; conflating the two would make a whole night of
    non-delivery invisible.
    """
    try:
        _message_evidence.record_said(
            loop, text, [asdict(reading) for reading in readings], recipient=recipient
        )
    except Exception as exc:  # noqa: BLE001 - Tier-2: the message already went; never re-fail the caller
        log.error("readings write failed (swallowed): %s", exc)


# The road name the MCP door's readings are stored under in `message_evidence`.
DOOR_ROAD = "door"

# Whose session a door reading belongs to. Always this today: the gateway's MCP
# client sends no session or run id to the door (checked on OpenClaw 2026.9.1,
# whose `x-openclaw-session-key` header exists only on its own inbound HTTP
# routes), so a reading cannot be tied to the run that made it. A reader of
# `door_readings` is reading every gateway session's window, and says so.
UNATTRIBUTED = ""

# A number as a tool writes one. `gh_issue_list` prints "42<TAB>OPEN ...",
# the worklist "Issue 42: ...", a person "#42". The door keeps every
# free-standing number and every commit sha of the WHOLE answer at the head of
# the excerpt, because the excerpt itself is capped and a long list would lose
# its tail. Shas go first: a whats_changed answer holds at most 40 of ten
# characters, while the numbers line has no such bound.
_READ_NUMBER_RE = re.compile(r"(?<!\d)\d{2,6}(?!\d)")


def remember_door_reading(
    tool: str,
    arguments: Mapping[str, Any] | None,
    outcome: str,
    result_text: str,
) -> None:
    """Keep one answer the MCP door handed out, for the send-time evidence check.

    Tier-2 like the rest of this seam: the answer has already gone to the
    caller, and a failed record must not turn a good read into a failure.
    """
    # Imported here: claims reaches this module through the write tools.
    from apps.assistant.core import claims

    numbers = sorted({int(found) for found in _READ_NUMBER_RE.findall(result_text)})
    header = (
        "shas read: " + " ".join(claims.cited_shas(result_text)) + "\n"
        "numbers read: " + " ".join(str(number) for number in numbers)
    )
    reading = Reading.of(tool, arguments, outcome, result_text)
    reading = replace(reading, excerpt=f"{header}\n{result_text}")
    try:
        _message_evidence.record_said(
            DOOR_ROAD, "", [asdict(reading)], recipient=UNATTRIBUTED
        )
    except Exception as exc:  # noqa: BLE001 - Tier-2: the answer already went
        log.error("door reading write failed (swallowed): %s", exc)


#: How far back a door reading still counts as evidence: half an hour,
#: since a brief or an advisor run reads and writes inside a few minutes.
DOOR_EVIDENCE_WINDOW_SECONDS = 30 * 60


def door_excerpts() -> list[str]:
    """The texts of every OK door reading inside the evidence window."""
    return [
        str(reading.get("excerpt", ""))
        for reading in door_readings(DOOR_EVIDENCE_WINDOW_SECONDS)
    ]


def door_readings(window_seconds: int) -> list[dict[str, Any]]:
    """Every OK door reading of the last `window_seconds`, from any session.

    Tier-1: the caller decides what a window it cannot read means.
    """
    now = datetime.now(timezone.utc)
    rows = _message_evidence.inputs_between(
        (now - timedelta(seconds=window_seconds)).isoformat(),
        (now + timedelta(seconds=1)).isoformat(),
        road=DOOR_ROAD,
    )
    return [
        reading
        for row in rows
        for reading in row["readings"]
        if reading.get("outcome") == READING_OK
    ]


def numbers_read(readings: Sequence[Mapping[str, Any]]) -> set[int]:
    """Every number those readings returned, issue numbers among them."""
    return {
        int(found)
        for reading in readings
        for found in _READ_NUMBER_RE.findall(str(reading.get("excerpt", "")))
    }


# Reasons a message was put in front of a person, used as the audit row's
# decision so the dead-letter watch and a human reading the table can tell the
# paths apart.
#
# `page` is the Alertmanager road. Without it, `page_hold.release` would write
# no delivery row at all: a release whose Signal send failed would log one line
# and leave its rows pending, so `monitor.dead_letters.check`, the watch for
# silent non-delivery, would be blind to the single wire in front of the
# loudest road.
DELIVERY_KINDS = ("beat", "morning", "monitor-page", "chat-reply", "page")

# Why a beat that could have spoken did not. A closed vocabulary, because the
# whole value of the record is that "it never told me" can be answered from
# data, and a free-text reason is a sentence nobody can count.
#
# The routes are the real ones and there are six, not one: a pass that did not
# finish and a pass that deliberately said QUIET are the same silence to a
# reader and completely different to whoever has to fix it.
# `quiet-hours-held` is not a seventh flavour of silence, it is the opposite of
# one: a patrol line written at night is HELD for the morning, which is not the
# same as a pass that had nothing to say, and one word for both would let an
# overnight finding either vanish or come back phrased as present news. The
# word says which of the two happened.
QUIET_REASONS = (
    "pass-faulted",
    "model-quiet",
    "stripped-to-nothing",
    "misaddressed",
    "quiet-hours",
    "quiet-hours-held",
)

# The fingerprint prefix a quiet-beat row carries. It keeps these rows out of
# every existing reader of the `alerts` table by construction: `unheard_silences`
# wants `decision='silent'`, `dead_letters_after` wants `dead_letter=1`, and
# `last_pen_page_at` / `pen_subject_delivered` / `recurring_alerts` all want a
# name beginning `pen flush (`. A quiet row has none of those shapes; keep it
# that way, because a quiet row that grew one of them would start being counted
# as a page nobody sent.
QUIET_FINGERPRINT_PREFIX = "beat:"


def record_quiet(beat: str, reason: str) -> None:
    """Write one audit row saying a beat had its chance and said nothing.

    THE HOLE THIS FILLS. Every guard in this system asks
    whether what the assistant SAID was true. None asks whether something should have
    been said, so silence is invisible: `patrol()` has four returns that produce
    no message and `advise()` two, and each one logs a line and writes nothing.
    Three patrol passes a day is twenty-one passes in a seven-day week, and a
    week in which the beat never once had anything worth saying is
    indistinguishable, from the data, from a week in which the model was broken
    and returned QUIET every time.

    `reason` must be one of `QUIET_REASONS`; an unknown one is recorded as
    given rather than dropped, because a reason nobody declared is still better
    evidence than no row, and the guard that catches it is a test rather than a
    raise on the paging path.

    Tier-2, and for the usual reason one layer along: a beat that stayed quiet
    has already done its job correctly, and failing it now to save a record of
    the silence would turn a bookkeeping fault into a broken beat.
    """
    try:
        state.record_alert(
            fingerprint=f"{QUIET_FINGERPRINT_PREFIX}{beat}",
            name=f"{beat} stayed quiet"[:200],
            severity="info",
            status="resolved",
            decision="quiet",
            reason=reason,
            signal_sent=False,
            dead_letter=False,
        )
    except Exception as exc:  # noqa: BLE001 - Tier-2: never break a quiet beat
        log.warning("quiet audit write failed for %s: %s", beat, exc)


def record_delivery(kind: str, subject: str, delivered: bool) -> None:
    """Write one audit row saying whether a message actually reached the phone.

    The audit answered "did we hand it off", never "did it arrive", and several
    layers treated the first as the second: `/webhook/notify` returns queued and
    its caller counted that as delivered; a beat route returns HTTP 200 with
    `delivered: false` in the body and the trigger exits 0; the notify pen wrote
    `dead_letter=False` even when the send had failed. So
    `monitor.dead_letters.check`, the watch for silent non-delivery, could
    only ever see rows the Alertmanager gate
    wrote, and was structurally blind to every beat, every page and every reply.

    A total Signal outage is still caught within about seventy minutes by the
    send canary. What escapes without this
    is the partial: one message, one recipient, one split piece. The morning
    brief's `mark_delivered()` is downstream of exactly that, so a brief that
    failed to send leaves tomorrow's brief re-narrating today's items as new.

    Tier-2: a failed audit write must never turn a delivery problem into a
    crash on the path that was already having trouble.
    """
    try:
        state.record_alert(
            fingerprint=f"delivery:{kind}",
            name=f"{kind}: {subject or '(no subject)'}"[:200],
            severity="info",
            status="firing",
            decision="delivered" if delivered else "not-delivered",
            reason=f"{kind} message",
            signal_sent=delivered,
            dead_letter=not delivered,
        )
    except Exception as exc:  # noqa: BLE001, Tier-2: never break the sender
        log.warning("delivery audit write failed for %s: %s", kind, exc)
