"""`alerts` table adapter, append-only audit of every alert + outcome.

Storage-grammar table adapter (blueprint §2.3): the table's write
(`record_alert`) and read (`list_recent_alerts`) live together.

FAILURE POLICY: Tier-1 fail-loud, a failed audit write propagates and
fails the webhook request (a known anti-pattern: never lose the audit
row silently).
"""
from __future__ import annotations

import datetime as _datetime
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from apps.assistant.core.state.conn import get_connection
from apps.assistant.core.state.utcnow_iso import utcnow_iso


# The `name` column's grammar for a BATCHED row, in one place because two
# readers parse it back: the morning brief's evidence bundle and the recurring
# observation filer. Composed by `core.notify_flush`, which is the only writer
# of batched rows.
_BATCH_PREFIX = "pen flush"
_BATCH_PREFIX_RE = re.compile(rf"^{_BATCH_PREFIX} \(\d+ pings?\):\s*")
_NAME_CHARS = 200


def batch_row_name(count: int, subjects: list[str]) -> str:
    """The audit name for one flushed batch: how many pings, and what about."""
    return f"{_BATCH_PREFIX} ({count} pings): {', '.join(subjects)}"[:_NAME_CHARS]


# The severity a sender marks on its own subject. Every sender in the stack does
# this and is consistent: a red circle for a build or deploy that failed, a
# cross for a systemd unit, a warning sign for a warning, a broom for routine
# housekeeping.
#
# The table has to hold EVERY marker in use. Two things break on a subject
# whose marker is missing. The subject reaches the phone with its product
# banner still on, because the banner strip runs behind a marker the split
# does not recognise and so matches nothing: the page opens "🟡 [the project]
# auto-deploy: ..." and spends characters of a short budget saying the
# reader's own product name back at them. And the recurring filer throws the
# whole audit row away as a legacy row, because a product banner inside a row
# name is exactly how it recognises one.
SEVERITY_MARKERS = (
    ("🔴", "critical"),
    ("⛔", "critical"),
    ("🚨", "critical"),
    ("❌", "error"),
    # The variation-selector spelling first: both are the warning sign, and
    # `startswith` would otherwise take the bare one and leave U+FE0F sitting
    # on the front of the subject.
    ("⚠️", "warning"),
    ("⚠", "warning"),
    # Amber. The step did not do its job and nothing failed outright: a gate
    # skipped, a GitHub API denied, a test selector that fell back to the full
    # suite. The deploy steps write more of these than of anything else.
    ("🟡", "warning"),
    ("🧹", "info"),
    # A deploy that worked, an e2e run that was all green, an alert that
    # resolved. The quietest thing a sender can say, and it must not read as
    # the same "info" an unmarked outage would.
    ("✅", "info"),
    ("🟢", "info"),
)
_SEVERITY_ORDER = ("info", "warning", "error", "critical")


def marked_severity(subject: str) -> str | None:
    """The severity the sender MARKED on `subject`, or None when none did.

    Three answers rather than two, and the third answer is the point.
    `severity_of_subject` below flattens "nobody marked this" into "info",
    which is right for a reader that only ranks one subject against another and
    wrong for anything that must not treat an unmarked subject as the quietest
    thing on the wire. Senders on the live stack that mark nothing at all
    (infra/nextcloud/session-lifetime-assert.sh among them) send
    outage-grade subjects.
    """
    head = str(subject or "").strip()
    for marker, severity in SEVERITY_MARKERS:
        if head.startswith(marker):
            return severity
    return None


def severity_of_subject(subject: str) -> str:
    """The severity a sender marked on `subject`; "info" when unmarked.

    The flattening is deliberate, and the recurring filer depends on it: it
    ranks subjects against each other and has no use for a third answer. Code
    that must tell "the sender called this routine" apart from "no sender said
    anything" asks `marked_severity` instead.
    """
    return marked_severity(subject) or "info"


def louder(left: str, right: str) -> str:
    """The louder of two severities. A batch is as serious as its worst ping;
    averaging would let one routine notice hide a failure."""
    def rank(value: str) -> int:
        try:
            return _SEVERITY_ORDER.index(str(value or "info").lower())
        except ValueError:
            return 0
    return left if rank(left) >= rank(right) else right


def is_batch_row_name(name: str) -> bool:
    """True when this audit row came from the notify pen, not Alertmanager.

    The two writers put very different things in `name`. The pen writes the
    subjects of the assistant's own pings ("systemd unit failed: harness-..."), one row
    per flushed batch. The Alertmanager gate writes the bare Prometheus
    alertname, and an alertname is a RULE GROUP name, not an incident: five
    rules share `ResourceHigh`, from an info-level load flake up to the
    critical disk-full page. Anything that acts per subject has to know
    which of the two it is holding.
    """
    return str(name or "").startswith(_BATCH_PREFIX + " (")


def subjects_in_row_name(name: str) -> list[str]:
    """The subjects behind an audit row, batch prefix removed.

    A row written by any other path is its own single subject, so this is safe
    to call on every row rather than only on batched ones.
    """
    stripped = _BATCH_PREFIX_RE.sub("", str(name or "")).strip()
    return [part.strip() for part in stripped.split(", ") if part.strip()]


# Decision values that mean "a road looked and decided to say nothing".
#
# THE VOCABULARY LIVES HERE because this is where the table's grammar lives:
# `is_batch_row_name`, `subjects_in_row_name`, the dead-letter predicate and the
# severity readers are all here, and a reader asking "what does this row mean"
# looks in the file named after the table. A prompt renderer is the wrong
# home for a storage grammar; `awareness` and `evidence` now re-export it from here.
#
# WHY IT EXISTS AT ALL. `outbound.record_quiet` writes "quiet" and
# `monitor/sweep.py` writes "digest-silent". Both rows are the assistant's own
# bookkeeping about its own silence rather than an event, and both prompt-facing
# readers of this table paste rows into a model's system prompt: `awareness`
# takes eight into every loop, `evidence` three into the morning brief. With the
# exclusion reverted and 21 quiet rows a week on the table, `evidence.alerts_fact()`
# answers "3 recorded, about: digest silenced: website down; patrol
# stayed quiet" and stays STATE_OK on a table holding nothing but silences, so
# The assistant narrates its own plumbing, which is the exact material
# `claims.own_plumbing` strips out of what the assistant SAYS.
#
# Excluded by DECISION and not by fingerprint prefix: the decision column is the
# one that says the row records a silence rather than a message, while a prefix
# filter would oblige every reader to learn a vocabulary of prefixes ("beat:",
# "monitor:") that only ever grows.
#: A beat that had its chance and said nothing (`outbound.record_quiet`).
SILENCE_QUIET_BEAT = "quiet"
#: A down component the monitor digest judged not worth saying (`monitor/sweep`).
SILENCE_DIGEST = "digest-silent"
SILENCE_DECISIONS = (SILENCE_QUIET_BEAT, SILENCE_DIGEST)

# The same exclusion as a SQL clause, which is what makes it cheap enough to
# use everywhere. A Python filter has to over-read to survive it: a reader that
# does not widen its row limit lets silence rows eat its budget before its own
# filter ever runs.
_NOT_A_SILENCE = "decision NOT IN ({})".format(
    ", ".join("?" for _ in SILENCE_DECISIONS)
)

# The fingerprint prefix `outbound.record_delivery` stamps on its own rows.
# Named here because two readers below fold on it.
DELIVERY_FINGERPRINT_PREFIX = "delivery:"

# The key `recent_alert_events` adds to a row it folded repeats into. Not a
# column: the table has no migrations, and this is a fact about one read rather
# than about the row.
FOLDED_REPEATS = "folded_repeats"

# How many rows are READ to answer for `limit` events. The silence exclusion is
# SQL now, so this headroom is only for the delivery fold below: on a failing
# night `page_hold.release` retries every 30 seconds, so four minutes of dead
# letters is eight rows of one kind and thirty-two is a quarter of an hour of
# them. A burst past that shows FEWER rows, never a wrong one.
_EVENT_SCAN_MULTIPLE = 4

# Row families that are the assistant's own stamp on its own road rather than something
# that arrived: a delivery record, a pen flush fingerprint, a quiet beat, a
# monitor digest silence. `subject_outcomes_between` drops identities in these
# families, because counting them as arrivals would make the busiest road look
# like the noisiest world.
NOT_AN_ARRIVAL = ("delivery:", "notify-pen:", "beat:", "monitor:")

# The decisions the assistant writes about its OWN handling of a fingerprint rather
# than about something that arrived on it. `page_hold._stamp_delivery` is the
# one that matters: it writes `status='firing'`, `decision='released'` on the
# alert's own fingerprint at release time, so a read that asks "what is the
# newest thing said about this key" gets the assistant's own stamp back and answers
# "still firing" for every page ever sent. The other three carry a prefixed
# fingerprint and cannot collide, and are named anyway so the list reads as
# what it is: everything in this table that is us talking about us.
OUR_OWN_HANDLING = ("released", "delivered", "not-delivered", "quiet")


def records_a_silence(row: Mapping[str, Any]) -> bool:
    """True when this audit row records a decision NOT to speak.

    Read by `awareness.render` and `evidence.alerts_fact`, the two readers that
    paste audit rows into a prompt a model then answers from. Kept as a row
    predicate as well as a SQL clause because a caller that already holds rows
    (a test, a replay) should not have to go back to the database to ask.
    """
    return str(row.get("decision") or "") in SILENCE_DECISIONS


@dataclass(frozen=True)
class SubjectOutcome:
    """One subject that arrived in a window, and whether anyone heard about it.

    `subject` is the row identity: the pen's own normalised subject on a batch
    row and the Alertmanager fingerprint everywhere else. `name` is the readable
    text for a report, which on an Alertmanager row is the alertname rather than
    the hex identity nobody can act on.
    """

    subject: str
    name: str
    rows: int
    delivered: bool


def record_alert(
    *,
    fingerprint: str,
    name: str,
    severity: str,
    status: str,
    decision: str,
    reason: str,
    signal_sent: bool,
    dead_letter: bool,
) -> int:
    """Append-only audit row. Returns the inserted row id."""
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO alerts (received_at, fingerprint, name, severity, status, "
            "decision, reason, signal_sent_at, dead_letter) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                utcnow_iso(),
                fingerprint,
                name,
                severity,
                status,
                decision,
                reason,
                utcnow_iso() if signal_sent else None,
                1 if dead_letter else 0,
            ),
        )
        conn.commit()
        return cursor.lastrowid or 0


def list_recent_alerts(limit: int = 50) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM alerts ORDER BY received_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def max_alert_id() -> int:
    """Highest audit row id, or 0 on an empty table.

    The dead-letter watch uses this as a starting watermark so a pod restart
    reports only what happens next, never replaying history.
    """
    with get_connection() as conn:
        row = conn.execute("SELECT MAX(id) AS max_id FROM alerts").fetchone()
    return int(row["max_id"] or 0) if row else 0


def dead_letters_after(row_id: int, limit: int = 20) -> list[dict[str, Any]]:
    """Alerts newer than `row_id` whose Signal delivery failed.

    A dead letter is a page the assistant decided to send and nobody received. It is
    the quietest possible failure: the decision looks right in the audit and
    the human simply never hears it.
    """
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM alerts WHERE id > ? AND dead_letter = 1 "
            "ORDER BY id ASC LIMIT ?",
            (row_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def alerts_since(
    since_iso: str, limit: int = 500, *, exclude_silences: bool = False
) -> list[dict[str, Any]]:
    """Audit rows received at or after `since_iso`, newest first.

    A window rather than a row count: how many alerts land in two weeks is not
    something a caller can guess, and guessing it low is how a recurring
    problem looks like a one-off.

    `exclude_silences` drops the bookkeeping rows IN THE SQL, before `limit`
    is applied, which is the only place it helps. `notify_flush._pen_history_rows`
    asks for 500 rows over 14 days and then keeps the pen-flush ones, so every
    quiet row and every digest silence spent one of those 500 before the filter
    ran: roughly 40% of the budget at 21 silences a week, on a read whose
    saturation flag makes the caller drop its per-subject ping history
    altogether. Filtering after a limit understates by construction.
    """
    clause = f" AND {_NOT_A_SILENCE}" if exclude_silences else ""
    parameters: tuple[Any, ...] = (since_iso,)
    if exclude_silences:
        parameters += SILENCE_DECISIONS
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM alerts WHERE received_at >= ?{clause} "
            "ORDER BY received_at DESC LIMIT ?",
            (*parameters, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def recent_alert_events(limit: int = 8) -> list[dict[str, Any]]:
    """The newest rows that record something HAPPENING, newest first.

    The read behind the two prompt blocks. It differs from `list_recent_alerts`
    in two ways, and both exist because those blocks are a fixed number of lines
    in front of a model rather than an audit a person scrolls.

    SILENCES ARE EXCLUDED IN SQL. See `SILENCE_DECISIONS` above: 21 quiet rows a
    week into an 8-row window is the assistant reading its own plumbing back to itself
    every loop.

    REPEATS OF ONE DELIVERY OUTCOME ARE FOLDED INTO THE NEWEST OF THEM, and this
    one is a judgement call rather than a cleanup, so it is argued here.
    `page_hold.release` retries a failed send every FLUSH_INTERVAL_SECONDS (30s)
    and `outbound.record_delivery` writes one row per attempt, so about four
    minutes into a Signal outage the whole 8-row window reads
    "page: ... -> not-delivered" eight times and the alert history the page was
    about is gone from every model loop's prompt. `evidence` reads three rows and
    fails harder. The pen has this shape too; the page road
    joined it and made it worse.

    There is a real argument that during a total send outage this IS the picture,
    and it is not dismissed: the fold keeps ONE line per delivery kind AND
    outcome, so "the page road is failing" still stands in the window, and the
    kept row carries `FOLDED_REPEATS` saying how many identical rows it stands
    for, so the reader is told the size rather than shown it eight times. What is
    refused is the same fact eight times at the price of the history. The alarm
    for a failing send road is `monitor.dead_letters`, which pages; this window
    is prompt input and was never the alarm.

    Folding on kind AND decision rather than kind alone, because a window holding
    seven failures and one success must not collapse to whichever came last.
    """
    scan = max(int(limit), 0) * _EVENT_SCAN_MULTIPLE
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM alerts WHERE {_NOT_A_SILENCE} "
            "ORDER BY received_at DESC, id DESC LIMIT ?",
            (*SILENCE_DECISIONS, scan),
        ).fetchall()
    return _delivery_folded([dict(row) for row in rows])[:limit]


def _delivery_folded(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Newest-first rows with each delivery kind's repeated outcome folded into
    the newest row carrying it, which then says how many it stands for."""
    kept: list[dict[str, Any]] = []
    newest: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        fingerprint = str(row.get("fingerprint") or "")
        if not fingerprint.startswith(DELIVERY_FINGERPRINT_PREFIX):
            kept.append(row)
            continue
        key = (fingerprint, str(row.get("decision") or ""))
        held = newest.get(key)
        if held is None:
            row[FOLDED_REPEATS] = 0
            newest[key] = row
            kept.append(row)
            continue
        held[FOLDED_REPEATS] = int(held[FOLDED_REPEATS]) + 1
    return kept


def delivery_counts_between(start_iso: str, end_iso: str) -> dict[str, int]:
    """How many messages each delivery kind recorded in the window.

    The only per-road denominator that exists, and it exists for two roads.
    `outbound.record_delivery` writes exactly one row per MESSAGE on both
    outcomes, so this counts messages sent and not messages delivered; a caller
    wanting the second reads `signal_sent_at` itself.
    """
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT fingerprint, COUNT(*) AS sent FROM alerts "
            "WHERE received_at >= ? AND received_at < ? AND fingerprint LIKE ? "
            "GROUP BY fingerprint",
            (start_iso, end_iso, f"{DELIVERY_FINGERPRINT_PREFIX}%"),
        ).fetchall()
    return {
        str(row["fingerprint"])[len(DELIVERY_FINGERPRINT_PREFIX):]: int(row["sent"])
        for row in rows
    }


def subject_outcomes_between(
    start_iso: str, end_iso: str
) -> tuple[SubjectOutcome, ...]:
    """Every subject that arrived in the window, and whether it was ever
    delivered about, oldest identity first.

    THE IDENTITY IS DERIVED THE WAY THE TABLE ALREADY ALLOWS, which is two ways
    because there are two writers. A pen flush names its subjects in the row
    name and counts pings in its fingerprint, so its identities come from
    `subjects_in_row_name`; every other row is its own single subject and its
    identity is the fingerprint, because an alertname is a rule GROUP shared by
    five rules of different severities.

    Rows in the `NOT_AN_ARRIVAL` families are not arrivals and are dropped by
    identity rather than by row: a delivery stamp, a quiet beat and a digest
    silence are the assistant talking about its own roads, and counting them here would
    say the busiest road was the noisiest world. The `notify-pen:` family is in
    that list for a case the branch above cannot reach: a pen row whose name was
    truncated past its grammar falls through to the fingerprint branch, and
    "notify-pen:3" must never enter a report as a subject.

    THIS COUNTS DECISIONS THE POD MADE, NEVER ARRIVALS AT ALERTMANAGER. A
    Watchdog routed to a null receiver, an inhibit rule, an operator silence, a
    group_wait fold, a 401 on the bearer and a 400 on a malformed body all leave
    zero rows here, so a night on which the webhook was broken reads as a night
    on which nothing arrived, and any headline built on this will say so
    confidently. Closing that needs a reading of Alertmanager's own state, which
    is a different source and not this one.
    """
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT name, fingerprint, signal_sent_at FROM alerts "
            "WHERE received_at >= ? AND received_at < ? "
            "ORDER BY received_at ASC, id ASC",
            (start_iso, end_iso),
        ).fetchall()
    ledger: dict[str, dict[str, Any]] = {}
    for row in rows:
        record = dict(row)
        for subject, readable in _identities_in(record):
            entry = ledger.setdefault(
                subject, {"name": readable, "rows": 0, "delivered": False}
            )
            entry["rows"] += 1
            entry["delivered"] = entry["delivered"] or bool(record["signal_sent_at"])
    return tuple(
        SubjectOutcome(
            subject=subject,
            name=str(entry["name"]),
            rows=int(entry["rows"]),
            delivered=bool(entry["delivered"]),
        )
        for subject, entry in ledger.items()
    )


def _identities_in(row: Mapping[str, Any]) -> list[tuple[str, str]]:
    """The (identity, readable name) pairs one audit row carries, arrivals only."""
    name = str(row.get("name") or "")
    if is_batch_row_name(name):
        found = [(subject, subject) for subject in subjects_in_row_name(name)]
    else:
        found = [(str(row.get("fingerprint") or ""), name)]
    return [
        (identity, readable)
        for identity, readable in found
        if identity and not identity.startswith(NOT_AN_ARRIVAL)
    ]


def has_delivered(fingerprint: str) -> bool:
    """True when a message about this fingerprint ever reached a phone.

    `record_alert` stamps `signal_sent_at` after the send was attempted, not
    when it was dispatched, so a non-null stamp is proof the human heard about
    this fingerprint at least once.

    Unbounded, and left that way on purpose for now. The same "ever" as an
    unwindowed pen read is here, and it is latent until a delivery is old
    enough for a silence to be swallowed by it. Windowing this one ALONE is
    what makes it
    worse rather than better, because `unheard_silences` below counts silences
    over the same unbounded table: bound the deliveries and leave the silences,
    and an old delivery stops counting while every old silence still does, so
    the streak is met at once, flipping fingerprints straight to `page-raw`.
    Both queries move together or neither does, and the
    caller in `core/triage.py` has to hand a window down.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS hits FROM alerts "
            "WHERE fingerprint = ? AND signal_sent_at IS NOT NULL",
            (fingerprint,),
        ).fetchone()
    return bool(row) and int(row["hits"] or 0) > 0


def last_delivered_at(fingerprint: str) -> str | None:
    """When a message about this fingerprint last reached a phone, or None.

    The page history triage is given and checks a silence against. A model
    rebuilding it from prompt rows that carry no fingerprint would read two
    UnitFailed alerts on different units as one, and a silence on the one that
    had never paged could cite the other's delivery time. Same unbounded
    "ever" as `has_delivered`, for the reason given there.
    """
    if not fingerprint:
        return None
    with get_connection() as conn:
        row = conn.execute(
            "SELECT MAX(signal_sent_at) AS sent FROM alerts "
            "WHERE fingerprint = ? AND signal_sent_at IS NOT NULL",
            (fingerprint,),
        ).fetchone()
    return str(row["sent"]) if row and row["sent"] else None


def delivered_pages_since(since_iso: str, limit: int = 8) -> list[dict[str, Any]]:
    """The alerts whose page reached a phone at or after `since_iso`, newest
    first, one per fingerprint, as `name`, `fingerprint` and `sent`.

    The candidates triage is shown when a silence describes its cover in prose
    and names none. The assistant's own row families are not alerts and are
    left out (`NOT_AN_ARRIVAL`).
    """
    excluded = " ".join(f"AND fingerprint NOT LIKE '{prefix}%'" for prefix in NOT_AN_ARRIVAL)
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT fingerprint, MAX(name) AS name, MAX(signal_sent_at) AS sent "
            "FROM alerts WHERE signal_sent_at IS NOT NULL AND signal_sent_at >= ? "
            f"{excluded} GROUP BY fingerprint ORDER BY sent DESC LIMIT ?",
            (since_iso, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def cleared_since(fingerprint: str, since_iso: str) -> str | None:
    """When this alert resolved after `since_iso`, or None while it still fires.

    The question `page_hold` asks before it lets an overnight page go: is the
    thing this page is about still happening? Alertmanager posts a `resolved`
    arrival the moment it stops, `gates/alertmanager` admits no third word, and
    `gates/app._record_alert` audits every arrival, so the answer is already in
    this table and needs no model and no second source.

    NEWEST WINS, which is what handles a flap. Resolved at 23:11 and firing
    again at 02:40 is firing, and a page that said it had cleared would be
    worse than the page that said nothing. So this reads the single newest
    arrival on the fingerprint and answers only when that one is a resolve.

    OUR OWN STAMPS ARE NOT ARRIVALS. See `OUR_OWN_HANDLING` above: without that
    exclusion the newest row on any released key is `page_hold`'s own
    `status='firing'` stamp, every answer is None, and the check is inert with
    every test green.
    """
    if not fingerprint:
        return None
    marks = ", ".join("?" for _ in OUR_OWN_HANDLING)
    with get_connection() as conn:
        row = conn.execute(
            "SELECT received_at, status FROM alerts "
            "WHERE fingerprint = ? AND received_at > ? "
            f"AND decision NOT IN ({marks}) "
            "ORDER BY received_at DESC, id DESC LIMIT 1",
            (fingerprint, since_iso, *OUR_OWN_HANDLING),
        ).fetchone()
    if not row or str(row["status"] or "") != "resolved":
        return None
    return str(row["received_at"])


def arrival_status_at(fingerprint: str, held_iso: str) -> str | None:
    """The status of the first arrival on this fingerprint at or after
    `held_iso`, or None when nothing has arrived since.

    `gates/app` holds a page BEFORE it audits the arrival that produced it, so
    for a held page this is the page's own arrival, and it says whether the
    page reports a firing or a resolve. `page_hold` asks it so a page saying a
    thing came back is never mistaken for a page about a thing that has since
    ended. The assistant's own stamps are not arrivals (`OUR_OWN_HANDLING`).
    """
    if not fingerprint:
        return None
    marks = ", ".join("?" for _ in OUR_OWN_HANDLING)
    with get_connection() as conn:
        row = conn.execute(
            "SELECT status FROM alerts "
            "WHERE fingerprint = ? AND received_at >= ? "
            f"AND decision NOT IN ({marks}) "
            "ORDER BY received_at ASC, id ASC LIMIT 1",
            (fingerprint, held_iso, *OUR_OWN_HANDLING),
        ).fetchone()
    return str(row["status"] or "") if row else None


def delivered_this_episode(fingerprint: str) -> str | None:
    """When a page about this fingerprint last reached a phone since the alert
    last resolved, or None when nothing has.

    One firing episode runs from a resolve (or the first arrival) to the next
    resolve. Alertmanager re-sends a firing warning every four hours and triage
    may draft a page for each re-send, so without this the same unresolved
    alert would leave `page_hold` day after day under one key. The
    resolve read excludes the assistant's own stamps for the same reason `cleared_since`
    does. An all-clear's own stamp carries `resolved` and is not counted: it
    ends this episode's story rather than opening the next one's.
    """
    if not fingerprint:
        return None
    marks = ", ".join("?" for _ in OUR_OWN_HANDLING)
    with get_connection() as conn:
        row = conn.execute(
            "SELECT MAX(signal_sent_at) AS sent FROM alerts "
            "WHERE fingerprint = ? AND signal_sent_at IS NOT NULL "
            "AND status != 'resolved' "
            "AND received_at > COALESCE(("
            "  SELECT MAX(received_at) FROM alerts WHERE fingerprint = ? "
            f"  AND status = 'resolved' AND decision NOT IN ({marks})"
            "), '')",
            (fingerprint, fingerprint, *OUR_OWN_HANDLING),
        ).fetchone()
    return str(row["sent"]) if row and row["sent"] else None


#: How recently a firing arrival must have come for an alert to count as still
#: firing. Alertmanager re-sends a firing alert every four hours, so twelve
#: hours is three missed re-sends: an alert whose resolve never arrived stops
#: counting after half a day instead of firing in this table for ever.
_STILL_FIRING_HOURS = 12

#: The severities a page goes out for. Info rows are the assistant's own road
#: (delivery records, beats) and never mean something is broken.
_PAGED_SEVERITIES = ("warning", "critical")


def firing_paged_names() -> list[str]:
    """The readable names of alerts that paged and are still firing, sorted.

    An alert counts when a page about it reached a phone in its current
    episode (`delivered_this_episode`), however long ago, and its newest
    arrival is a firing one from the last `_STILL_FIRING_HOURS`. Read by
    `message_teammate`, which refuses an all-clear while one of these stands:
    without it a brief can say "nothing broke overnight" seconds after
    paging a service down, and keep saying "nothing broken" for days while
    an alert it paged once still fires.
    """
    since = (
        _datetime.datetime.now(_datetime.timezone.utc)
        - _datetime.timedelta(hours=_STILL_FIRING_HOURS)
    ).isoformat()
    severities = ", ".join("?" for _ in _PAGED_SEVERITIES)
    not_ours = " ".join("AND fingerprint NOT LIKE ?" for _ in NOT_AN_ARRIVAL)
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT fingerprint, MAX(name) AS name FROM alerts "
            f"WHERE severity IN ({severities}) AND signal_sent_at IS NOT NULL "
            f"{not_ours} GROUP BY fingerprint",
            (*_PAGED_SEVERITIES, *(f"{prefix}%" for prefix in NOT_AN_ARRIVAL)),
        ).fetchall()
    names = {
        str(row["name"] or row["fingerprint"])
        for row in rows
        if delivered_this_episode(str(row["fingerprint"]))
        and _fires_since(str(row["fingerprint"]), since)
    }
    return sorted(names)


def _fires_since(fingerprint: str, since_iso: str) -> bool:
    """True when the newest arrival on this fingerprint is a firing one that
    came at or after `since_iso`. The assistant's own stamps are not arrivals."""
    marks = ", ".join("?" for _ in OUR_OWN_HANDLING)
    with get_connection() as conn:
        row = conn.execute(
            "SELECT received_at, status FROM alerts WHERE fingerprint = ? "
            f"AND decision NOT IN ({marks}) "
            "ORDER BY received_at DESC, id DESC LIMIT 1",
            (fingerprint, *OUR_OWN_HANDLING),
        ).fetchone()
    return bool(
        row
        and str(row["status"] or "") == "firing"
        and str(row["received_at"]) >= since_iso
    )


def unheard_silences(fingerprint: str) -> int:
    """Judged silences on a fingerprint that has never delivered a message.

    Returns 0 as soon as any delivered row exists for the fingerprint, so a
    resolve of something that WAS paged is never counted. Mechanical silences
    (the 5-minute dedup window, an operator suppression) are excluded: those
    are not judgements and must never manufacture a streak.

    Read by the triage silence floor. The case it exists for: every row on
    one critical fingerprint `silent` with `signal_sent_at` NULL while the
    fault kept firing.
    """
    if has_delivered(fingerprint):
        return 0
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS hits FROM alerts WHERE fingerprint = ? "
            "AND decision = 'silent' AND status = 'firing' "
            "AND reason != 'dedup-window-hit' "
            "AND reason NOT LIKE 'suppressed:%'",
            (fingerprint,),
        ).fetchone()
    return int(row["hits"] or 0) if row else 0


def silences_since(fingerprint: str, since_iso: str) -> int:
    """Judged silences on a firing of this fingerprint received after
    `since_iso`, with the same mechanical exclusions as `unheard_silences`.

    Triage's page history quotes it, so the model does not invent the count
    (two different counts hours apart on one fingerprint).
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS hits FROM alerts WHERE fingerprint = ? "
            "AND decision = 'silent' AND status = 'firing' AND received_at > ? "
            "AND reason != 'dedup-window-hit' "
            "AND reason NOT LIKE 'suppressed:%'",
            (fingerprint, since_iso),
        ).fetchone()
    return int(row["hits"] or 0) if row else 0


def last_pen_page_at(*, since: str) -> str | None:
    """When the pen last put a page on the wire, None if it did not since
    `since`.

    The flusher's pacing input, and it lives here rather than on the pen table
    because the pen table cannot answer the question. `notify_pen.mark_flushed`
    stamps `flushed_at` on every ping it takes out of the queue, a batch judged
    to be noise and a batch already on the board included, so a pacing read of
    MAX(flushed_at) over the whole pen would let a flush that SENT NOTHING
    start a full 300-second story gap, and the next tick's real page would
    wait behind a silence. It is not an edge case: most flushes go quiet, so
    the pen would sit in a near-permanent gap of its own making.

    A page that was composed and handed to Signal counts here whether or not
    Signal took it, which is why the read is on the two delivery columns rather
    than on the decision: `signal_sent_at` is a page that landed and
    `dead_letter` is a page that did not, and both mean the pen already said
    this. The undelivered one is retried with the SAME text on a later tick, so
    letting it restart the gap is what stops a Signal outage from costing one
    model call every 30 seconds. A judged silence sets neither column, and that
    is the whole difference this function exists to draw.

    `since` is required for the reason it is required on `pen_subject_delivered`
    below: the table is append-only and pruned by nothing, so an unbounded MAX
    would scan the lot to answer a question that only ever concerns the last few
    minutes. Anything older than the story gap has already passed the gap, so
    None and "the gap is over" are the same answer.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT MAX(received_at) AS latest FROM alerts "
            "WHERE name LIKE ? AND received_at >= ? "
            "AND (signal_sent_at IS NOT NULL OR dead_letter = 1)",
            (f"{_BATCH_PREFIX}%", str(since)),
        ).fetchone()
    return row["latest"] if row else None


def pen_subject_delivered(subject: str, *, since: str) -> bool:
    """True when a delivered pen flush carried this exact subject since
    `since`.

    The pen writes one audit row per BATCH, not per ping, and its fingerprint
    counts pings rather than naming them, so `has_delivered` cannot answer this
    question. The subjects themselves are in the row name, normalised by the
    flusher before they get there, which is what makes the match reliable
    enough to gate a page on.

    Read by the notify-pen floor. Without it, flush after flush carrying
    "auto-deploy: verification gate RED" can be judged noise and never reach a
    phone, for hours in which nothing can ship.

    `since` is required, because without it the floor would be disarmed
    permanently. The whole `alerts` table is append-only and pruned by nothing
    (no DELETE anywhere in openclaw), so one delivered row, ever, would be
    enough, and every later flush on the subject, including a fresh outage the
    next day, would be judged noise. The window is not
    a matter of taste here, it is the whole mechanism, so there is no default
    for a caller to forget.

    A truncated row name can only fail to match, never match wrongly, so an
    imperfect read errs toward saying it once too often rather than never.
    """
    text = str(subject or "").strip()
    if not text:
        return False
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS hits FROM alerts "
            "WHERE name LIKE ? AND signal_sent_at IS NOT NULL "
            "AND name LIKE ? AND received_at >= ?",
            (f"{_BATCH_PREFIX}%", f"%{text}%", str(since)),
        ).fetchone()
    return bool(row) and int(row["hits"] or 0) > 0
