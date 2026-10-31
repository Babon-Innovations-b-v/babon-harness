"""What arrived, what nobody was told about, and what is deliberately waiting.

The claim audit's second acceptance line: "an alert that fired and reached no person is
a countable number". This module is that count, and most of its length is spent
on the three ways of getting it wrong.

A JUDGED SILENCE IS THE NORMAL CASE. Most pen flushes go quiet and that is
correct: the pen exists to give summaries rather than a page per ping. So `unheard` is legitimately non-zero on a good
week and is not, on its own, something to act on. `unheard_critical` is the
number worth a person's Monday: a subject that could be the first word about an
outage and that nobody heard. It uses `notify_flush._may_be_critical`, which
treats an UNMARKED subject as possibly critical, rather than a severity rule
invented here; six senders on the live stack mark nothing at all and they send
outage-grade subjects.

A HELD PAGE IS NOT AN UNHEARD ONE, and this is the distinction that decides
whether the number is useful at all. The pen's quiet-hours hold, the pen's
story-gap hold and `page_hold`'s quiet-hours and pacing holds write NOTHING to
`alerts`; they are durable only as pending rows in `notify_pen` and `page_hold`.
A held page is the largest single silence the assistant produces, and it is
the one silence that is deliberate and correct.
Counted into `unheard` it would make the headline read as a fault every night
the brake worked, so it is counted separately and rendered separately.

THE THREE TABLES ARE READ IN ONE PASS, IN ONE ORDER, and the moment is reported
with the counts. The answer is assembled from `alerts`, `notify_pen` and
`page_hold`, and a release landing between two reads makes it disagree with
itself: a page released after the alerts read and before the page_hold read is
counted in neither. `at` is stamped before the first read, so the reader is told
which moment the numbers describe rather than being left to assume they share
one.

THE RISK THAT IS WRITTEN DOWN RATHER THAN SOLVED. This counts DECISIONS THE POD
MADE, never arrivals at Alertmanager. A Watchdog routed to a null receiver, an
inhibit rule, an operator silence, a group_wait fold, a 401 on the bearer and a
400 on a malformed body all leave zero rows in `alerts`, so a night on which the
webhook was broken reads here as a night on which nothing arrived, and the
headline will say so confidently. Closing that gap needs a reading of
Alertmanager's own state, which is a different source and a different effort;
until then the report says this out loud where a person can see it.

FAILURE POLICY: Tier-1 fail-loud. A window that could not be read must never
answer zero: "nobody was left unheard" for a database nobody could open is the
one wrong answer nobody questions.
"""
from __future__ import annotations

from dataclasses import dataclass

from apps.assistant.core import state


@dataclass(frozen=True)
class Silence:
    """One window's silence, split into the three things it is made of."""

    at: str
    subjects: int
    unheard: tuple[str, ...]
    unheard_critical: tuple[str, ...]
    held_pings: int
    held_pages: int

    @property
    def held(self) -> int:
        """Everything waiting on purpose, on both roads."""
        return self.held_pings + self.held_pages


def between(since_iso: str, until_iso: str) -> Silence:
    """The window's arrivals, its silences and what is still deliberately held.

    One pass, one order: `alerts` first because it is the window, then the two
    pending queues, which are a reading of NOW rather than of the window. That
    is not a mismatch to fix: a page held right now is the reason a subject in
    the window looks unheard, so the two belong in one answer with one stamp
    saying when it was taken.
    """
    at = state.utcnow_iso()
    outcomes = state.subject_outcomes_between(since_iso, until_iso)
    held_pings = state.pending_ping_count()
    held_pages = state.pending_page_count()
    silent = tuple(one.name for one in outcomes if not one.delivered)
    return Silence(
        at=at,
        subjects=len(outcomes),
        unheard=silent,
        unheard_critical=tuple(name for name in silent if _may_be_critical(name)),
        held_pings=held_pings,
        held_pages=held_pages,
    )


def _may_be_critical(subject: str) -> bool:
    """Whether this subject could be the first word about an outage.

    Borrowed from `notify_flush`, not re-derived, for the same reason
    `claim_audit.check` borrows the claim rules: a checker with a severity rule
    of its own reports what its own rule thinks rather than what the live floor
    thinks, and the difference between the two is a fact about the checker. It
    is a private name in that module and is called as one deliberately, because
    promoting it would change the live paging path to make a weekly report
    tidier.
    """
    from apps.assistant.core import notify_flush

    return notify_flush._may_be_critical(subject)
