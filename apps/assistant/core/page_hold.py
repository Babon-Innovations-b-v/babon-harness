"""The one brake in front of the phone.

The assistant composes messages on two roads, and without this module they would reach a phone on two.
The notify pen collects pings, holds them overnight and composes one page when
the morning opens. The Alertmanager road runs triage, which investigates with
real tools and writes a draft, and then sent that draft itself the moment it had
one.

Only the first road had brakes. Without this module a busy night can put
many messages on a phone between 22:00 and 07:30 local, all of them on the
triage road, while the pen contributes one, at 07:30, holding and merging
everything it took that night.

So the roads merge HERE, at the wire, and not in the composer. Each keeps the
way it writes, because they know different things: the pen composes from typed
facts under the house rules, and triage writes prose after a tool loop that
actually looked at the system. What they share is the clock.

WHAT THIS IS NOT. It is not a second quiet-hours rule, and it is not a
composer: it never asks a model anything, it packs finished text and stamps what
left. `flush_pen` keeps its own overnight hold, because holding unread pings is
cheap and holding a written page is not the same act; see the note in
`state/page_hold.py`.

A PAGE THAT IS NO LONGER NEWS IS DROPPED, NOT SENT. A page held
all night can be about a fault that ended before anyone read it, such as a
"container is down since 23:06" released at 09:00 local, with the resolve on
that fingerprint in the `alerts` table since 23:11. The rule is that an outage which ended is a line in
the morning report, not a page, and that "down since" about a thing that came
back is worse than saying nothing. And one firing episode is one page per
`limits.REPAGE_AFTER_HOURS` (12): Alertmanager re-sends a firing warning
every four hours, and a fold that only compared rows waiting at the same
moment would page one unresolved alert day after day. The window has an end because a fault that never resolves would
otherwise be paged once and never again, with every later page triage
wrote about it dropped. `_no_longer_news` answers both with SELECTs on the table `_stamp_delivery`
writes to, keyed on the fingerprint the held row carries. It asks no model and
writes no text.

THE MORNING. Without a gate, two things would reach the phone half an hour
apart for no reason but the clock: the pen releasing everything it held when
the quiet window ends, and the brief. So the end of quiet hours is not a
send, and `_morning_gate_shut` holds what
the window released until the morning's message is due.

The gate does not wait for the brief to ARRIVE in this queue: the brief is
written by the gateway on its own cron and sent on its own channel, so it never
joins this queue. `ASSISTANT_MORNING_GATE_UNTIL` IS the release, one clock and
nothing to wait for, and it moved to the brief's own hour so the night lands
beside the report rather than an hour behind it. The queue fills every day while
the brief is Monday to Friday, so the gate opening on the clock is also what
stops a Saturday night being held until Monday, which is a silence dressed as
calm.

The pen asks that question rather than joining this queue for the rest of the
day, through `morning_gate_shut`, which is public for exactly that caller. It
still composes and sends on its own pacing everywhere else; inside the morning
window it queues its page here instead, so the night leaves in one message.
Putting that road behind this brake all day would be the second brake this
file's first paragraph refuses, with a second story gap in front of a road that
already paces itself.

ON A BRIEF DAY THE NIGHT GOES IN THE BRIEF. A gate opening at 08:00 would
send the night as its own message in the same minute the brief starts, so the
morning would still be two messages; a held page belongs in the morning
report. So on the brief's weekdays the gate stays shut past 08:00 until the brief has landed
(a `teammate-self` send to the page recipient since the gate's hour), for at
most `ASSISTANT_BRIEF_WAIT_MINUTES` (30). The brief lists what is held, read
through `my_actions`; a held page whose subject the delivered brief names is
stamped released at the brief's minute and never sent again, and every page it
does not name leaves on its own straight after, as before. A brief that never
runs, fails, or leaves a page out therefore costs a late page, never a lost one,
and a weekend opens at 08:00 as it always did.

Public callables: `release(now=None)`, `morning_gate_shut()`, `hold_beat()`,
`held_recently()`, `SUBJECT_JOIN` and `SUBJECT_CHARS`.

WHAT A RELEASE RECORDS, and why it is two rows and not one. `_stamp_delivery` writes one `alerts` row per released KEY, which
is what `triage._silence_floor` reads, so it counts FINGERPRINTS: four keys in
one message are four rows. `record_delivery("page", ...)` writes one row per
MESSAGE, on both outcomes, and it is the row that was missing entirely. On the
failure side it is the fix: this release was the only send path left in the container
that wrote nothing when Signal refused, so `monitor.dead_letters.check`, the
dead-letter watch, was structurally blind to the single
wire in front of the loudest road. On the success side it is the denominator:
without it the road reports failures against a count of messages that exists
nowhere, and a rate nobody can compute is a rate nobody checks. It costs one
extra row per released message, which is real: `awareness.render` pastes the
newest eight `alerts` rows into every model loop's prompt.

FAILURE POLICY: Tier-2 for the send, Tier-1 for the bookkeeping. A Signal
failure leaves every row pending and a later pass retries, because a page that
was never delivered must not be marked as though it were. Later, not next: the
flusher calls `release` every 30 seconds, and without a backoff a seven-hour Signal
outage becomes hundreds of sends and not-delivered rows. So a failed
send waits 30 seconds, then doubles up to 15 minutes, and the message that
finally lands says it is late and why. A state error
propagates: this queue is now the single thing standing between both roads and
the phone, and a release pass that swallows its own faults is a silent night
that looks like a quiet one. `record_delivery` is itself Tier-2 inside
`outbound`, so a failed audit write cannot turn a delivery problem into a crash
on the path that is already in trouble.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from apps.assistant.core import outbound as _outbound
from apps.assistant.core import quiet_hours as _quiet_hours
from apps.assistant.core import state as _state
from apps.assistant.core.state import chat_turns as _chat_turns
from apps.assistant.core.limits import REPAGE_AFTER_HOURS, SIGNAL_MAX_CHARS
from apps.assistant.core.tools.meta.whats_changed import REPORT_SCHEDULES
from apps.assistant.shared import local_time as _local_time
from apps.assistant.shared import signal as _signal_dispatch

log = logging.getLogger("openclaw.page_hold")

#: How long one page's news stays one story. The same constant the pen paces
#: itself with, imported rather than copied, because two roads sharing a clock
#: that disagree about the length of a minute share nothing.
from apps.assistant.core.notify_flush import (  # noqa: E402
    STORY_GAP_SECONDS,
)

#: The separator between two composers' work inside one message. A blank line
#: and nothing else: a header would be a banner, and the one-voice rule says a
#: page does not announce which part of the assistant wrote it.
_JOIN = "\n\n"

#: When the morning gate opens, "HH:MM" local, from `ASSISTANT_MORNING_GATE_UNTIL`.
#: The default is the hour the gateway sends the brief, so the night that was
#: held through quiet hours lands beside it rather than an hour behind. It is a
#: clock and not a wait: nothing else can open this gate, and a queue with no way
#: to open on its own would hold a Saturday night until Monday morning. A silent
#: night that looks like a quiet one is the failure this whole queue exists to
#: make impossible.
_GATE_UNTIL_ENV = "ASSISTANT_MORNING_GATE_UNTIL"
_GATE_UNTIL_DEFAULT = "08:00"

#: The weekdays the gateway sends the morning brief, from the one copy of its
#: schedule the container carries (pinned to the gateway's cron by a test there).
_BRIEF_WEEKDAYS = REPORT_SCHEDULES["morning"].weekdays

#: How long past the gate's hour a brief day waits for the brief to land before
#: the night leaves on its own. A brief takes a few minutes of tool calls.
_BRIEF_WAIT_ENV = "ASSISTANT_BRIEF_WAIT_MINUTES"
_BRIEF_WAIT_DEFAULT = 30

#: The `chat_turns.loop` a send nobody asked for is booked under, which is what
#: the brief's `message_teammate` call writes once it is delivered.
_BRIEF_LOOP = "teammate-self"

#: How a page carrying several subjects joins them (the pen's night page). Each
#: one must be named by the brief for the page to count as carried.
SUBJECT_JOIN = "; "

#: The longest subject `hold_beat` keeps.
SUBJECT_CHARS = 120

#: How many leading words of a subject the brief must repeat to have named it.
_NAMED_WORDS = 5

#: How long a delivered page keeps later pages on its still-firing fingerprint
#: out. The triage prompt states the same window from the same constant.
_REPAGE_AFTER = timedelta(hours=REPAGE_AFTER_HOURS)

#: The wait after the first failed send, doubled per failure up to the cap.
_RETRY_FIRST_SECONDS = 30
_RETRY_MAX_SECONDS = 15 * 60


@dataclass
class _SendOutage:
    """Signal refusing this road's sends: since when, how often, and when to
    try next. In memory on purpose, like the dead-letter watermark: a restart
    that retries at once costs one send."""

    failures: int = 0
    since: datetime | None = None
    next_try_at: datetime | None = None


_outage = _SendOutage()


def release(now: datetime | None = None) -> str | None:
    """Send what is due, hold what is not, and return the text that went out.

    The gates run in `flush_pen`'s order and for `flush_pen`'s reasons, because
    a second brake that disagreed with the first would be two brakes:

    1. Nothing at all pending, nothing to do. A keyed page that is no longer
       news (its alert resolved, or this firing episode was already paged) is
       taken out of the queue here, at any hour, and never sent.
    2. Quiet hours and the morning gate: hold everything except a critical.
       This is the whole point of the merge. A page written in the small hours is
       not less true after breakfast, and most such pages are nothing a person
       could act on at two in the morning that they could not act on later.
       An alert whose severity is `critical` is the exception: it leaves at
       once, alone, without the story gap, because a critical red held until
       morning is a whole night of an outage nobody was told about.
       Warnings and info keep the hold.
    3. The story gap: inside it, keep collecting, unless the oldest waiting page
       has itself waited a full gap, which is the catch-up path for a release
       pass that was down.
    4. Newest per key. A road that has lost its own quieting cannot stack seven
       drafts about one fingerprint into one morning message.
    5. Pack under the Signal cap, send ONE message, stamp what fitted AND what
       the fold replaced. What did not fit stays pending rather than being
       dropped with a trailer saying so.

    Returns None when nothing left, which is the normal answer.
    """
    moment = now or datetime.now(timezone.utc)
    waiting = _without_stale(_state.pending_pages(), moment)
    if not waiting:
        return None

    held_because = _held_because(moment)
    if held_because is not None:
        critical = [row for row in waiting if _is_critical(row)]
        log.info(
            "%s: holding %d page(s), releasing %d critical",
            held_because,
            len(waiting) - len(critical),
            len(critical),
        )
        if not critical:
            return None
        return _send(_newest_per_key(critical), waiting, moment)

    waiting = _without_carried(waiting, moment)
    if not waiting or _paced_out(waiting, moment):
        return None

    return _send(_newest_per_key(waiting), waiting, moment)


def _held_because(moment: datetime) -> str | None:
    """Which clock is holding the queue right now, or None when neither is."""
    if _quiet_hours.quiet_now(moment):
        return "quiet hours"
    if _morning_gate_shut(moment):
        return "morning gate"
    return None


def _is_critical(row: dict) -> bool:
    """Whether this held page is about an alert whose severity is critical.

    The severity is the Alertmanager label `gates/app._hold_page` copied in
    when the page was queued. The pen's rows and `hold_beat`'s carry none, so
    they are never critical here and keep the hold.
    """
    return str(row.get("severity") or "").strip().lower() == "critical"


def _send(due: list[dict], waiting: list[dict], moment: datetime) -> str | None:
    """Pack `due` into one message, send it, and stamp what it accounts for."""
    if _outage.next_try_at is not None and moment < _outage.next_try_at:
        return None
    lead = _late_line(moment)
    text, sent_ids = _packed(due, reserved=len(lead))
    if not text:
        return None
    if lead:
        text = f"{lead}\n{text}"
    # On the local clock here and not only inside `send`, so the copy
    # `remember_sent` keeps is the text the owner read.
    text = _local_time.in_local_time(text, moment)

    delivered = _signal_dispatch.send(subject="", body=text)
    # Before the branch, and on both outcomes: one row per MESSAGE, which is
    # the count this road never had. See "WHAT A RELEASE RECORDS" above.
    _outbound.record_delivery("page", _what_left(due, sent_ids), delivered)
    if not delivered:
        # Tier-2: leave every row pending. A later pass retries, and a page
        # marked released that never arrived is exactly the kind of quiet
        # failure this queue exists to make impossible.
        _note_failed_send(moment)
        log.error(
            "page_hold: send failed, %d page(s) stay pending until %s",
            len(sent_ids),
            _outage.next_try_at,
        )
        return None

    _outage.failures, _outage.since, _outage.next_try_at = 0, None, None
    stamped = _released_ids(waiting, due, sent_ids)
    _state.mark_released(stamped, now=moment.isoformat())
    _outbound.remember_sent("", text, worklist_items=_items_of(due, sent_ids))
    _stamp_delivery(due, sent_ids)
    log.info(
        "page_hold: released %d of %d pending page(s) as %d paragraph(s), %d chars",
        len(stamped),
        len(waiting),
        len(sent_ids),
        len(text),
    )
    return text


def _note_failed_send(moment: datetime) -> None:
    """Count one failed send and push the next try out, doubling to the cap."""
    _outage.failures += 1
    if _outage.since is None:
        _outage.since = moment
    wait = min(_RETRY_FIRST_SECONDS * 2 ** (_outage.failures - 1), _RETRY_MAX_SECONDS)
    _outage.next_try_at = moment + timedelta(seconds=wait)


def _late_line(moment: datetime) -> str:
    """The line that opens a message Signal held up, or "" when none did."""
    if _outage.since is None:
        return ""
    return (
        f"Late: Signal stopped delivering at {_clock(_outage.since)} "
        f"and came back at {_clock(moment)}, so this waited."
    )


def _clock(moment: datetime) -> str:
    """HH:MM on the quiet-hours clock, the zone every page is read in."""
    minute = _quiet_hours.local_minute(moment)
    return f"{minute // 60:02d}:{minute % 60:02d}"


def morning_gate_shut(now: datetime | None = None) -> bool:
    """Is the morning still holding, right now? Asked by the pen.

    The pen composes and sends on its own road, so it needs the ANSWER rather
    than the brake. Public because a second copy of this clock in
    `notify_flush` is exactly the drift `quiet_hours.ends_at_minute` exists to
    prevent; the rule itself stays in one place, here.
    """
    try:
        # `now` is passed through rather than materialised: every clock read
        # under here already treats None as "the moment this is asked", on
        # `quiet_hours`' own zone, which is the zone the window is defined in.
        return _morning_gate_shut(now)
    except Exception:  # Tier-2: an unreadable clock must never hold a page
        log.exception("page_hold: could not read the morning gate; not holding")
        return False


def hold_beat(
    text: str,
    *,
    subject: str = "",
    road: str = "beat",
    worklist_items: tuple[int, ...] = (),
) -> None:
    """Queue one beat's message instead of sending it.

    The advisor and the recurring-alerts line going straight out through
    `_send_beat` would make a morning carry several messages. Held here they
    wait for whatever leaves next, which in the morning is the brief.
    No key: a beat is only ever itself, so there is nothing for the fold to
    collapse, and the pen's own pages are keyless for the same reason.
    `worklist_items` are the items the beat is about, which the release writes
    onto the chat turn for the chat relay.

    Tier-2. A beat that cannot be queued is logged and dropped rather than
    raised, because these routes are advisory and a failed hold must not 500 a
    timer; the brief and the pen are the paths that may never lose a message.
    """
    if not text or not text.strip():
        return
    try:
        _state.hold_page(
            text,
            road=road,
            subject=subject[:SUBJECT_CHARS],
            worklist_items=",".join(str(item_id) for item_id in worklist_items),
        )
    except Exception:  # Tier-2: an advisory beat never 500s a timer
        log.exception("page_hold: could not queue a beat; dropping it")


def held_recently(limit: int = 10) -> list[dict]:
    """The pages waiting right now, for the two model loops' don't-repeat block.

    Triage decides whether to speak by reading what the assistant already said, and
    that read goes through `chat_turns`, which is only written after a send. A
    held page is not there, so without this block triage stops seeing "already
    paged" and stops silencing the follow-ups, most of which cite a page a
    hold would have prevented.
    """
    return _state.recent_held(limit)


def _morning_gate_shut(now: datetime | None) -> bool:
    """True while the morning's pages should wait for the morning.

    WHY. The overnight hold can work perfectly and the morning still go wrong:
    when the window ends, each composer takes its own turn inside the next
    hour or two (the pen releases what it held, then the brief, the
    recurring-alerts line and the weekly advisor). Nothing repeats and nothing
    is wrong; there are simply several messages where one is wanted, and the
    first fires before the report it belongs in, for no reason other than that
    the quiet window happens to end there.

    So the end of quiet hours stops being a send: between it and the morning's
    own hour the queue stays shut. Opening it on the brief arriving here would
    be the neat version, and it is not true, because the brief runs on the
    gateway's cron and its own channel. A gate waiting for
    something that cannot arrive is not a gate, it is the deadline wearing one,
    so the deadline is the whole rule now.

    With quiet hours switched off entirely there is no morning to speak of, so
    there is no gate either.
    """
    ends_at = _quiet_hours.ends_at_minute()
    if ends_at is None:
        return False
    minute = _quiet_hours.local_minute(now)
    deadline = _gate_deadline_minute()
    # The morning is the stretch between the end of the quiet window and the
    # deadline. A window that wraps past the deadline (someone set the quiet
    # hours to end at 10:00) leaves no morning at all rather than an inverted
    # one that would hold all day.
    if ends_at <= minute < deadline:
        return True
    return _waiting_for_the_brief(now, minute, deadline)


def _waiting_for_the_brief(now: datetime | None, minute: int, deadline: int) -> bool:
    """True on a brief day between the gate's hour and the end of the wait,
    while the brief has not landed yet.

    Tier-2: a brief that cannot be read opens the gate, because the cost of
    guessing wrong that way is a page sent beside the brief, and the cost of
    the other is a page held for no reason.
    """
    if not deadline <= minute < deadline + _brief_wait_minutes():
        return False
    local = _quiet_hours.local_moment(now)
    if local.weekday() not in _BRIEF_WEEKDAYS:
        return False
    try:
        return _todays_brief(local) is None
    except Exception:  # Tier-2: an unreadable brief never holds a page
        log.exception("page_hold: could not read whether the brief landed; not waiting")
        return False


def _brief_wait_minutes() -> int:
    """`ASSISTANT_BRIEF_WAIT_MINUTES`, the default when unset or unreadable."""
    raw = os.environ.get(_BRIEF_WAIT_ENV, "").strip()
    if raw.isdigit():
        return int(raw)
    if raw:
        log.warning("malformed %s=%r; using %d", _BRIEF_WAIT_ENV, raw, _BRIEF_WAIT_DEFAULT)
    return _BRIEF_WAIT_DEFAULT


def _todays_brief(local: datetime) -> dict | None:
    """The first send nobody asked for that reached the page recipient since
    today's gate hour, as {text, created_at}, or None. Raises on a state fault."""
    destination = _outbound.recipient()
    if destination is None:
        return None
    deadline = _gate_deadline_minute()
    opened = local.replace(
        hour=deadline // 60, minute=deadline % 60, second=0, microsecond=0
    ).astimezone(timezone.utc)
    sent = _chat_turns.sent_to_since(destination, _BRIEF_LOOP, opened.isoformat())
    return sent[0] if sent else None


def _without_carried(waiting: list[dict], moment: datetime) -> list[dict]:
    """The waiting pages minus the ones today's brief already told the reader
    about, which are stamped released at the brief's minute and never sent.

    Only on a brief day, only pages held before the brief landed, and only a
    page whose every subject the brief names (`_named_in`). Anything else stays
    and leaves as its own message, so a brief that left a page out costs a late
    page and never a lost one. Tier-2 on the read for the same reason.
    """
    local = _quiet_hours.local_moment(moment)
    if local.weekday() not in _BRIEF_WEEKDAYS:
        return waiting
    try:
        brief = _todays_brief(local)
    except Exception:  # Tier-2: the pages still go
        log.exception("page_hold: could not read today's brief; sending the night")
        return waiting
    if brief is None:
        return waiting
    landed = _moment(brief["created_at"])
    carried = [
        row for row in waiting
        if _moment(row["held_at"]) <= landed and _named_in(row, brief["text"])
    ]
    if not carried:
        return waiting
    ids = [int(row["id"]) for row in carried]
    _state.mark_released(ids, now=landed.isoformat())
    _stamp_delivery(carried, ids)
    log.info("page_hold: the morning brief carried %d held page(s)", len(ids))
    return [row for row in waiting if int(row["id"]) not in ids]


def _named_in(row: dict, text: str) -> bool:
    """Whether `text` names every subject this page carries, by its leading
    `_NAMED_WORDS` words, ignoring case and spacing. A page with no subject is
    never named."""
    said = _plain(text)
    parts = [part for part in str(row.get("subject") or "").split(SUBJECT_JOIN) if part.strip()]
    return bool(parts) and all(
        " ".join(_plain(part).split()[:_NAMED_WORDS]) in said for part in parts
    )


def _plain(text: str) -> str:
    """Case folded and whitespace collapsed, the spelling `_named_in` compares."""
    return " ".join(str(text).casefold().split())


def _gate_deadline_minute() -> int:
    """`ASSISTANT_MORNING_GATE_UNTIL` as minutes since local midnight.

    Anything unreadable falls back to the default rather than raising: this
    sits in front of the phone, and a malformed environment variable must not
    be able to decide that nothing is sent today.
    """
    raw = os.environ.get(_GATE_UNTIL_ENV, _GATE_UNTIL_DEFAULT).strip()
    match = re.match(r"^(\d{1,2}):(\d{2})$", raw)
    if match is None or int(match.group(1)) > 23 or int(match.group(2)) > 59:
        if raw != _GATE_UNTIL_DEFAULT:
            log.warning(
                "malformed %s=%r; using %s", _GATE_UNTIL_ENV, raw, _GATE_UNTIL_DEFAULT
            )
        match = re.match(r"^(\d{1,2}):(\d{2})$", _GATE_UNTIL_DEFAULT)
    return int(match.group(1)) * 60 + int(match.group(2))


def _paced_out(waiting: list[dict], now: datetime) -> bool:
    """True while the story gap is still collecting rather than sending."""
    last = _state.last_release_at()
    if last is None:
        return False
    gap = now - _moment(last)
    oldest = now - _moment(waiting[0]["held_at"])
    return gap < timedelta(seconds=STORY_GAP_SECONDS) and oldest < timedelta(
        seconds=STORY_GAP_SECONDS
    )


def _newest_per_key(waiting: list[dict]) -> list[dict]:
    """One page per key, the newest, with keyless rows all kept.

    A keyless row is the pen's, and the pen has already merged its own batch
    into one page, so there is nothing left to fold. A keyed row is triage's,
    one per alert fingerprint, and seven drafts about one expired token is the
    shape this drops.
    """
    newest: dict[str, dict] = {}
    keyless: list[dict] = []
    for row in waiting:
        if not row.get("key"):
            keyless.append(row)
            continue
        held = newest.get(row["key"])
        if held is None or row["held_at"] >= held["held_at"]:
            newest[row["key"]] = row
    together = keyless + list(newest.values())
    return sorted(together, key=lambda row: (row["held_at"], row["id"]))


def _without_stale(waiting: list[dict], moment: datetime) -> list[dict]:
    """The waiting pages minus the ones that are no longer news, which are
    stamped out of the queue with their reason and never sent."""
    kept: list[dict] = []
    for row in waiting:
        reason = _no_longer_news(row, moment)
        if reason is None:
            kept.append(row)
            continue
        _state.mark_dropped([int(row["id"])], reason=reason, now=moment.isoformat())
        log.info("page_hold: dropped held page %s (%s): %s", row["id"], row["key"], reason)
    return kept


def _no_longer_news(row: dict, moment: datetime) -> str | None:
    """Why this held page should never be sent, or None when it should.

    Already paged means paged inside `_REPAGE_AFTER` of `moment`; an older
    page in the same episode no longer speaks for this one.

    A KEYLESS ROW IS ALWAYS NEWS. The pen's page merges a whole night of pings
    and `hold_beat`'s carries no identity at all, so neither has a fingerprint
    to ask about.

    A page whose own arrival was a resolve is a page saying the thing came
    back, and it stays: it is about the ending, so the ending cannot make it
    stale.

    Tier-2, alone in this file. Everything else here propagates, because a
    release pass that swallows its own faults is a silent night that looks like
    a quiet one; but a read that fails here must cost the drop, never the page.
    """
    key = str(row.get("key") or "")
    if not key:
        return None
    try:
        held = _moment(row["held_at"]).astimezone(timezone.utc).isoformat()
        cleared = _state.cleared_since(key, held)
        # A group page is keyed by its leader alone; while a sibling it speaks
        # for still fires, the leader's recovery does not make it old news.
        siblings_cleared = all(
            _state.cleared_since(fingerprint, held) for fingerprint in _covered(row)
        )
        if cleared and siblings_cleared and _state.arrival_status_at(key, held) != "resolved":
            return f"its alert resolved at {cleared}"
        said = _state.delivered_this_episode(key)
        recent = bool(said) and moment - _moment(said) < _REPAGE_AFTER
        only_raw = recent and _checked_after_raw(row, key)
    except Exception:  # Tier-2: the page still goes
        log.exception("page_hold: could not check whether %s is still news", key)
        return None
    if recent and not only_raw:
        return f"this firing was already paged at {said}"
    return None


def _checked_after_raw(row: dict, key: str) -> bool:
    """Whether this held page is the checked version of an unchecked one.

    A "[RAW] " page says nothing was looked at, so it must not stop the
    diagnosis written after it, or the enriched page for the same alert, held
    seconds later, would be dropped as already paged."""
    if str(row.get("text") or "").startswith("[RAW] "):
        return False
    return str(_state.last_released_text(key) or "").startswith("[RAW] ")


def _released_ids(
    waiting: list[dict], due: list[dict], sent_ids: list[int]
) -> list[int]:
    """Every pending row this message accounts for, the folded ones included.

    THE LEAK THIS CLOSES. If only the ids of the rows that SURVIVED
    `_newest_per_key` reached `mark_released`, then, since nothing in openclaw
    deletes from `page_hold` or vacuums it, one fingerprint firing twice would
    leave one row pending for good.

    The cost is not the orphan row, it is the brake. `state.pending_pages`
    orders by `held_at`, `_paced_out` measures the story gap from `waiting[0]`,
    and an age that only ever grows is permanently past `STORY_GAP_SECONDS`. So
    from the first fold onward the pass would stop collecting and send every
    page the moment it was written, on the one wire in front of both composers.
    The orphan would also ride along in every later message, because
    `_newest_per_key` would keep picking it up again.

    Stamped rather than deleted: the table is the audit of what was held and
    when it left, and the replaced draft's news did leave, inside the newer
    draft that took its place. A keyless row (the pen's) is only ever itself,
    so it is accounted for by `sent_ids` alone.
    """
    keys = {
        row["key"]
        for row in due
        if int(row["id"]) in sent_ids and row.get("key")
    }
    accounted = set(sent_ids)
    for row in waiting:
        if row.get("key") in keys:
            accounted.add(int(row["id"]))
    return sorted(accounted)


def _items_of(due: list[dict], sent_ids: list[int]) -> tuple[int, ...]:
    """The worklist item ids the pages in this message are about, first named first.

    Read off the rows that went into the message, so the chat relay can tell
    the chat which item a reply answers.
    """
    ids: list[int] = []
    for row in due:
        if int(row["id"]) not in sent_ids:
            continue
        for part in str(row.get("worklist_items") or "").split(","):
            if part.strip().isdigit() and int(part) not in ids:
                ids.append(int(part))
    return tuple(ids)


def _what_left(due: list[dict], sent_ids: list[int]) -> str:
    """What this message was about, for the delivery row's name.

    `monitor.dead_letters.check` renders these names straight into its Talk
    post, so "(no subject)" would report a lost page as an unnamed one. The
    pen's rows carry no subject of their own, and a count is the honest thing
    to say about them rather than a subject invented here.
    """
    subjects: list[str] = []
    for row in due:
        subject = str(row.get("subject") or "").strip()
        if int(row["id"]) in sent_ids and subject and subject not in subjects:
            subjects.append(subject)
    return ", ".join(subjects) or f"{len(sent_ids)} page(s)"


def _packed(due: list[dict], reserved: int = 0) -> tuple[str, list[int]]:
    """As many whole pages as fit under the Signal cap less `reserved`
    characters for a lead line, and their row ids.

    Whole pages only. A page cut in half is worse than a page that waits, and
    what does not fit is not dropped: it stays pending and leaves on the next
    pass, which is the one behaviour the old `_join_drafts` trailer could not
    offer because it had nowhere to put the remainder.
    """
    kept: list[str] = []
    ids: list[int] = []
    used = reserved
    for row in due:
        cost = len(row["text"]) + len(_JOIN)
        if kept and used + cost > SIGNAL_MAX_CHARS:
            break
        kept.append(row["text"])
        ids.append(int(row["id"]))
        used += cost
    return _JOIN.join(kept), ids


def _stamp_delivery(due: list[dict], sent_ids: list[int]) -> None:
    """Record that the keyed pages in this message were delivered.

    Not optional bookkeeping. `triage._silence_floor` asks `has_delivered` about
    a fingerprint and force-pages every second silence when the answer is no, so
    a road whose rows never say delivered force-pages for ever. The row is
    written when the page LANDS rather than when it was queued, which is the
    same lesson `gates/app` learned: audit what happened, not what
    was intended.

    One row per key, so this counts fingerprints and not messages; the message
    is counted once by `record_delivery` in `release`. A row folded away by
    `_newest_per_key` shares its key with the row that replaced it and is
    therefore already stamped by that one.
    """
    landed = [
        row for row in due if int(row["id"]) in sent_ids and row.get("key")
    ]
    for row in landed:
        # The key, and every fingerprint of the same cause the page spoke for,
        # or a sibling's next lone triage finds no delivery and pages raw.
        for fingerprint in [row["key"], *_covered(row)]:
            _stamp_one(row, fingerprint)


def _covered(row: dict) -> list[str]:
    """The fingerprints besides its key that a held page speaks for."""
    return [part for part in str(row.get("covers") or "").split(",") if part]


def _stamp_one(row: dict, fingerprint: str) -> None:
    """Write one delivered row on `fingerprint` for the page `row` sent.

    An all-clear is stamped `resolved`, because `delivered_this_episode` counts
    only firing deliveries: stamped `firing` it would read as the next
    episode's page and drop that episode's first real one."""
    try:
        _state.record_alert(
            fingerprint=fingerprint,
            name=row["subject"] or row["key"],
            severity=row["severity"] or "info",
            status="resolved" if _reports_a_resolve(row) else "firing",
            decision="released",
            reason="held page released from the queue",
            signal_sent=True,
            dead_letter=False,
        )
    except Exception as exc:  # noqa: BLE001, Tier-2: the page already left
        log.warning(
            "page_hold: could not stamp delivery for %s: %s", fingerprint, exc
        )


def _reports_a_resolve(row: dict) -> bool:
    """Whether this held page was written about its alert ending."""
    held = _moment(row["held_at"]).astimezone(timezone.utc).isoformat()
    return _state.arrival_status_at(str(row["key"]), held) == "resolved"


def _moment(text: str) -> datetime:
    """An ISO timestamp out of the table, always tz-aware."""
    moment = datetime.fromisoformat(text)
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
