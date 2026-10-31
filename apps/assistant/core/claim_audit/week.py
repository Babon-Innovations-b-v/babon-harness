"""A window of sent messages, each judged against its own recorded readings.

The reading half of the audit: one state query, then `check.check` per row. It
sends nothing and it writes nothing, which is what keeps a report about noisy
messages from being another message.

FAILURE POLICY: Tier-1 fail-loud, like the state adapter under it. A window
that cannot be read is a report that must not be printed: a claim audit
answering "nothing to report" for a database it could not open is the one wrong
answer nobody would question.
"""
from __future__ import annotations

from dataclasses import dataclass

from apps.assistant.core import state
from apps.assistant.core.claim_audit.check import Finding, check


@dataclass(frozen=True)
class Judged:
    """One sent message and what the rules found in it."""

    loop: str
    said_at: str
    text: str
    findings: tuple[Finding, ...]
    readings: int


def judged_between(since_iso: str, until_iso: str) -> tuple[Judged, ...]:
    """Every recorded message in the window, judged, oldest first.

    All of them and not only the ones with findings, because the denominator is
    half the report: four findings in nine messages and four in four hundred
    are different weeks.
    """
    return tuple(
        Judged(
            loop=row["loop"],
            said_at=row["said_at"],
            text=row["text"],
            findings=check(row["text"], row["readings"]),
            readings=len(row["readings"]),
        )
        for row in state.message_evidence.said_between(since_iso, until_iso)
    )


def findings_between(since_iso: str, until_iso: str) -> tuple[Judged, ...]:
    """Only the messages in the window that something was found in."""
    return tuple(one for one in judged_between(since_iso, until_iso) if one.findings)
