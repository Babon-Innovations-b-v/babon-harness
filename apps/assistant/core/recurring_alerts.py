"""File a recurring own-alert observation as a backlog issue, once.

`file_recurring_observations() -> list[Filed]` and `announce(filed) -> str` are
the module. The first looks at openclaw's own alert audit, finds a subject that
keeps coming back, opens ONE sub-issue for it under the backlog PRD (`backlog_prd` in `.claude/project.json`),
and suppresses that subject so it never pages again. The second renders the one
line that says so. Filing without saying so would be worse than the paging it
replaces: the alert would go quiet and nobody would know where it went.

Why this exists. A failure that recurs every night, paged every time and
raised in every morning brief, costs attention each time and changes nothing.
A thing that comes back every night is not news on any of those nights: it is
a piece of work, and work belongs on the board where it waits without costing
anyone attention.

The rule: the assistant carries a recurring subject of its own alerts only
until it files it. Then it names the issue once and never raises it again.

The mute lives in `state.filed_observations`, deliberately NOT in the
suppression table. That one is the ALERT pipeline's mute, and using it here
silences an alert in order to quieten a message, which hides a live
condition from the people it pages. The record carries the issue number,
so anyone reading it sees where the work went, it is also what stops the filer
opening a second card tomorrow, and it expires.

FAILURE POLICY: Tier-2 best-effort, end of the line. Nothing here may break the
beat that calls it: a bad read returns [], and a subject that fails to file is
skipped with a log line and retried next pass. The suppression is written ONLY
after the issue exists, so a failed create can never silence a subject that has
no home to go to.
"""
from __future__ import annotations

from apps.assistant.shared.project import AREA_LABEL_PREFIX, AREAS, BACKLOG_PRD, OWNER_LOGIN

from apps.assistant.shared.name import ASSISTANT_NAME

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from apps.assistant.core import state
from apps.assistant.core.ping_facts import mute_key
from apps.assistant.core.tools.gh import github_act

log = logging.getLogger("openclaw.recurring_alerts")


@dataclass(frozen=True)
class Filed:
    """One recurring subject that now has a card and no longer pages."""

    number: int
    subject: str

# The standing backlog issue and the owner, from .claude/project.json. A
# recurring alert is filed as a bug under the backlog when one is configured,
# and loose otherwise.
_BACKLOG = BACKLOG_PRD
_ASSIGNEE = OWNER_LOGIN
_LABELS = ([f"{AREA_LABEL_PREFIX}{AREAS[0]}"] if AREAS else []) + ["bug"]

# What "keeps coming back" means. Both halves matter: five pings inside one
# crash loop is one event, and it is the second and third NIGHT that make a
# thing worth a card on the board rather than a page.
_WINDOW_DAYS = 14

# How many audit rows the fortnight read may bring back. See the call site for
# why it is stated rather than defaulted.
_WINDOW_ROW_LIMIT = 2000
_MIN_OCCURRENCES = 3
# THREE DAYS, NOT TWO, AND THE DAY COUNT IS THE ONLY VARIABLE THAT SEPARATES
# THE CLASSES. Subjects tend to have no middle: most fire on ONE day, a few on
# two, and almost none on three or more. The two-day band is mostly a single
# bad afternoon, a sender re-firing while something upstream is stuck, and
# filing at two days yields false positives: the same condition spelled
# differently, a repair that succeeded, a sender bug already fixed. Three
# separate days is the shape this module is for, such as a nightly job that
# keeps reporting the same thing.
#
# Raising `_MIN_OCCURRENCES` instead does not work: a burst inflates
# occurrences far faster than days, so an occurrence bar high enough to
# exclude one bad hour would also exclude a real problem that shows up quietly
# once a day.
_MIN_DISTINCT_DAYS = 3

# One pass files at most this many, so a noisy fortnight cannot open a dozen
# cards in one go.
_MAX_PER_PASS = 2

# Severities this may never file away. Filing writes a suppression with no
# expiry and no un-suppress path anywhere, so the cost of being wrong is
# permanent deafness on that subject.
# Never muted automatically, whatever the count. A sender marks its subject 🔴
# for a build or a deploy that failed, and those are the alerts that tell us
# shipping is broken; muting one would hide a stuck deploy from the only alert
# that says so. Everything quieter than this the assistant may mute on
# its own, announced and expiring; a red one waits for a person.
_NEVER_FILE_SEVERITIES = frozenset({"critical", "page"})

# The product banner a sender used to leave in the subject. Its presence marks a
# row written by an older sender, when subjects were also cut to 40 characters
# and the unit name did not survive.
_LEGACY_BANNER_RE = re.compile(r"\[[^\]]+\]")


def _window_start() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=_WINDOW_DAYS)).isoformat()


def _recurring_subjects() -> list[tuple[str, int, set[str]]]:
    """Subjects seen often enough, and on enough separate days, to be work.

    Returns `(subject, occurrences, days)`, most-seen first.

    Two things are deliberately excluded, and both are the difference between
    filing a nuisance and going deaf.

    Alertmanager rows, because an alertname is a RULE GROUP, not an incident.
    `ResourceHigh` is five Prometheus rules under one name, from an
    info-level load flake up to the critical disk-full page, and
    `is_suppressed` matches on that name. Filing it would silence a critical
    disk alert permanently, possibly the one for the filesystem whose filling
    up can leave the assistant mute. The rule is that the assistant carries
    what the owner's own alert system keeps showing them, which is the notify pen; a
    Prometheus rule already has a human-operated suppression path.

    And anything that arrived critical inside the window, whatever wrote it,
    read from the audit row's severity column AND from the marker the sender put
    on the subject. A thing that keeps coming back AND is sometimes critical is
    not noise to file away, it is an unfixed incident.
    """
    try:
        # The limit is named here rather than left at the read's default of
        # 500, because that window is cut at the OLD end and this caller has no
        # saturation check: a window that came back full has silently dropped
        # the earliest rows, which is exactly the repeats this function exists
        # to find. The silence record adds a row every time a beat stays quiet,
        # which eats into the default's headroom, so the number is set here
        # instead of being discovered later as a filer that had quietly gone
        # blind.
        rows = state.alerts_since(_window_start(), limit=_WINDOW_ROW_LIMIT)
    except Exception as exc:  # noqa: BLE001, Tier-2: the beat outlives a bad read
        log.warning("recurring-alert read failed: %s", exc)
        return []
    seen: dict[str, list[str]] = {}
    critical: set[str] = set()
    for row in rows:
        if not state.is_batch_row_name(row.get("name")):
            continue
        if _LEGACY_BANNER_RE.search(str(row.get("name") or "")):
            # A legacy row: its subjects still carry the product banner AND
            # were cut to 40 characters, so what survives is a few letters of
            # a unit name, shared by every unit with the same prefix.
            #
            # Skipping them is not tidiness. The subject IS the mute key, and it
            # has to equal what a live ping computes today or the mute does
            # nothing. Filing from such a row would tell the owner a subject had
            # stopped paging while muting a string no ping will ever produce: a
            # card nobody can act on, under a promise that is not true. It waits for real rows instead.
            continue
        received_at = str(row.get("received_at") or "")
        subjects = state.subjects_in_row_name(row.get("name"))
        # Two places the severity can live, and both have to be read.
        #
        # The COLUMN is right only for rows written after the
        # pen started recording what senders mark. Every older row was
        # stamped "info" whatever it was.
        #
        # The MARKER survives in the subject of those older rows, because the
        # banner-stripping landed the same day. So an old row still says 🔴 in
        # its text while its column says info, and a new row says critical in
        # its column with the marker already stripped out of its text. Reading
        # only one of the two leaves half the history mislabelled, which would leave
        # the assistant offering to mute a critical alert.
        # Attribute severity PER SUBJECT, from the marker its own sender wrote.
        # A batch row carries up to four subjects and one severity column, so
        # the column can only ever describe the loudest ping on the row. Using
        # it alone would let one red ping blacklist every subject beside it,
        # silently making an unrelated recurring failure unfileable.
        #
        # The column is still the fallback, and only for rows written in the
        # window where markers were being stripped, which are few.
        # There the row is all we know, so the whole row is treated as loud.
        #
        # Both sets are keyed by `mute_key`, the spelling the mute itself is
        # written under, so a subject that was critical in ANY spelling is
        # unfileable: refusing only the marked spelling would let the bare one
        # sitting on an older row still be filed.
        marked = [state.severity_of_subject(subject) for subject in subjects]
        if any(level != "info" for level in marked):
            for subject, level in zip(subjects, marked):
                if level.lower() in _NEVER_FILE_SEVERITIES:
                    critical.add(mute_key(subject))
        elif str(row.get("severity") or "info").lower() in _NEVER_FILE_SEVERITIES:
            critical.update(mute_key(subject) for subject in subjects)
        for subject in subjects:
            seen.setdefault(mute_key(subject), []).append(received_at)
    recurring = []
    for subject, arrivals in seen.items():
        if subject in critical:
            continue
        days = [moment[:10] for moment in _undecided(subject, arrivals)]
        if len(days) >= _MIN_OCCURRENCES and len(set(days)) >= _MIN_DISTINCT_DAYS:
            recurring.append((subject, len(days), set(days)))
    recurring.sort(key=lambda item: item[1], reverse=True)
    return recurring


def _undecided(subject: str, arrivals: list[str]) -> list[str]:
    """The arrivals of `subject` that came after the last decision about it.

    A card that was filed and then lifted, or that lapsed, was a decision on
    the occurrences before it. Counting them again would refile a lifted
    subject within a day, off the very rows that produced the first card. An unreadable decision answers no arrivals: a duplicate card
    is worse than a card one beat late.
    """
    try:
        decided_at = state.last_decision_at(subject)
    except Exception as exc:  # noqa: BLE001, Tier-2: skip, retry next pass
        log.warning("last-decision read failed for %r: %s", subject, exc)
        return []
    if decided_at is None:
        return arrivals
    return [moment for moment in arrivals if moment > decided_at]


def _already_filed(subject: str) -> bool:
    """True when the assistant has already filed this, or an operator has silenced it.

    Both count. Either a card already exists, or a human decided this does not
    need a page; opening another card would be arguing with one of them.
    """
    try:
        if state.filed_issue_for(subject) is not None:
            return True
        suppressed, _ = state.is_suppressed(subject)
    except Exception as exc:  # noqa: BLE001, Tier-2: skip, retry next pass
        log.warning("filed/suppression read failed for %r: %s", subject, exc)
        return True  # unknown means do not file: a duplicate card is worse
    return suppressed


def _issue_body(subject: str, occurrences: int, days: set[str]) -> str:
    return (
        f"{ASSISTANT_NAME} filed this: `{subject}` fired {occurrences} times on "
        f"{len(days)} separate days in the last {_WINDOW_DAYS} days, and self-"
        "cleared each time.\n\n"
        "It is on the board because it keeps coming back, not because it is "
        f"urgent. {ASSISTANT_NAME} will not page about it for {state.FILED_TTL_DAYS} days; "
        "the alert itself is not suppressed, and closing this issue is what "
        "decides whether it was real.\n\n"
        f"Days it fired: {', '.join(sorted(days))}\n\n"
        f"{ASSISTANT_NAME} raises this once and will not raise it again."
    )


def _file_one(subject: str, occurrences: int, days: set[str]) -> Filed | None:
    """Open the card and silence the subject, in that order. What was filed,
    or None when nothing was."""
    result = github_act.execute(
        {
            "action": "create",
            "title": f"Recurring alert: {subject}"[:70],
            "body": _issue_body(subject, occurrences, days),
            "assignee": _ASSIGNEE,
            "add_labels": _LABELS,
            **({"parent": _BACKLOG} if _BACKLOG is not None else {}),
        },
        actor="assistant",
    )
    number = github_act.issue_number_in(result)
    if number is None:
        log.warning("filing %r did not produce an issue: %s", subject, result)
        return None
    # Only now. A mute written before the issue exists quietens a subject with
    # nowhere to go, which is the failure this module exists to prevent rather
    # than cause.
    #
    # `record_filed`, NOT `add_suppression`. The suppression table is the ALERT
    # pipeline's mute: triage consults it and returns silent without an LLM
    # call. Using it here would silence an alert, possibly a rule group with a
    # critical page in it, in order to quieten a message. This mutes the assistant's message
    # and nothing else, and unlike a suppression it expires.
    state.record_filed(subject, number)
    return Filed(number=number, subject=subject)


def file_recurring_observations() -> list[Filed]:
    """File every subject that keeps coming back, and silence it. Returns what
    the caller may mention once."""
    filed: list[Filed] = []
    for subject, occurrences, days in _recurring_subjects():
        if len(filed) >= _MAX_PER_PASS:
            break
        if _already_filed(subject):
            continue
        try:
            one = _file_one(subject, occurrences, days)
        except Exception as exc:  # noqa: BLE001, Tier-2: skip, retry next pass
            log.warning("filing %r failed: %s", subject, exc)
            continue
        if one is not None:
            filed.append(one)
            log.info("filed recurring alert %r as #%s", subject, one.number)
    return filed


def announce(filed: list[Filed]) -> str:
    """The one line that says where a recurring alert went, "" when nothing
    was filed.

    Deterministic, with no model in the path, for the same reason the coverage
    footer is: this sentence is the entire difference between filing something
    and quietly silencing it, and it may not be lost to a nudge, a strip or a
    budget cap.
    """
    if not filed:
        return ""
    parts = [f"{one.subject} is now #{one.number}" for one in filed]
    return (
        f"{' and '.join(parts)} under the dev backlog: it kept coming back, so "
        "it is on the board and I have stopped paging about it."
    )
