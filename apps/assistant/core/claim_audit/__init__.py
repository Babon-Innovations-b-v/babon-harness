"""Claim audit: what the assistant SAID, checked against what the assistant READ.

Every guard in `core/claims.py` runs on a draft, before the message leaves, and
may nudge the model once. This package runs the same rules a week later, on the
messages that actually went out, and may only report. Nothing here sends,
nudges or blocks, and that is the point: a report about noisy messages must not
be another message.

It is possible because `core/state/message_evidence.py` keeps the readings
behind every message. Without that every message is durable and not one
reading behind it is, so a sentence like "recovered from last night's low
after your prune" cannot be checked against anything an hour after it was
sent.

Module map:

    check.py   `check(message_text, readings) -> tuple[Finding, ...]`: one
               message against its own readings. `Finding` is that call's
               signature type and rides with it
    week.py    `judged_between(since, until)` / `findings_between(...)`: a
               window of recorded messages, each judged. `Judged` rides here
    render.py  `report(judged, since, until, coverage, silence)`: the text a
               person reads on a Monday, grouped by rule
    coverage.py `between(since, until)`: what share of what the assistant sent carries
               its readings, per road, with an exact road-blind total beside it
    silence.py `between(since, until)`: what arrived, what nobody was told
               about, and what is deliberately still waiting

THE RULES ARE BORROWED, NEVER COPIED. `check.py` calls `claims.SENTENCE_RULES`
and the whole-message guards by name and defines no pattern of its own; a test
reads this package for `re.compile` and fails on one. A checker with rules of
its own reports messages the guards were always going to allow, which is a fact
about the checker.

AND WHAT THE ASSISTANT DID NOT SAY, COUNTED. `coverage` and
`silence` are the other half of the same weekly picture: the audit above asks
whether what was said was supported, and those two ask what share of it was
recorded at all and what never got said to anybody. They ride in this package
rather than in a package of their own because they are read on the same Monday,
through the same bearer-gated route, by the same timer, and a second timer with
a second Talk post would be five new files to answer half a question.

WHAT NEITHER HALF CAN SEE. A delivery failure. Messages that never reach
the assistant, for instance across a restart, and no reading of outbound text can
find a message that was never sent. That half is the
unanswered-inbound count, which is a warning and never a critical.

FAILURE POLICY: Tier-1 fail-loud on the read (`week.py`), pure everywhere else.
An audit that answers "nothing to report" for a window it could not read is the
one wrong answer nobody questions.
"""
from __future__ import annotations

# Re-exported as the submodule (not its callable): `report` is a generic verb
# and collides with the several report seams in `core/`; callers use
# `claim_audit.render.report(...)`.
from apps.assistant.core.claim_audit import coverage, render, silence

# Signature types ride with their callables and ARE re-exported flat
#, as they are on the `core` seam.
from apps.assistant.core.claim_audit.check import Finding, check
from apps.assistant.core.claim_audit.week import (
    Judged,
    findings_between,
    judged_between,
)

__all__ = [
    "Finding",
    "Judged",
    "check",
    "coverage",
    "findings_between",
    "judged_between",
    "render",
    "silence",
]
