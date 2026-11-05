"""A sent message is judged only against the readings that answered, and a number no read returned is a finding.

WHAT IT PINS. `claim_audit.check`, the weekly said-versus-seen judgement of one
sent message against the readings recorded beside it: an issue number no
successful read returned is `fabricated_issue_numbers`, a reading whose tool
answered nothing (`unavailable`) is no evidence at all, a hand-off command is
`command_syntax`, and a plain message or an empty one carries no finding.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The messages and
readings are made up here, and each expected rule list follows from what the
reading did or did not return: #4711 appears in the first reading's text and
in no other, and `unread_stamp` fires only where a successful reading exists
and lacks the number, since with no evidence at all it cannot judge.

ONE FUNCTION. This module's one test. A new check is a parametrized case of
it, never a second function.

WHAT IT WAS PROVED AGAINST. The break in this test's register row lets an
unavailable reading count as evidence, so the unavailable case finds nothing.

GUARDS. One test per module (#1210), 2026-11-05.
"""
from __future__ import annotations

import pytest

from apps.assistant.core.claim_audit import check

SAID = "Issue #4711 is open and assigned to Sam."


def _read(tool: str, excerpt: str, outcome: str = "ok") -> dict:
    return {"outcome": outcome, "tool": tool, "excerpt": excerpt}


CASES = [
    pytest.param(SAID, [_read("gh_issue_view", "#4711 open, assignee sam")], (), id="backed-by-the-read"),
    pytest.param(SAID, [_read("gh_issue_view", "#12 open")], ("unread_stamp", "fabricated_issue_numbers"),
                 id="a-number-no-read-returned"),
    pytest.param(SAID, [_read("gh_issue_view", "#4711 open", outcome="unavailable")], ("fabricated_issue_numbers",),
                 id="an-unavailable-read-is-no-evidence"),
    pytest.param("Run journalctl -u harness-webhook.service to see it.", [], ("command_syntax",),
                 id="a-hand-off-command"),
    pytest.param("Good morning, nothing new overnight.", [], (), id="a-plain-message"),
    pytest.param("   ", [], (), id="an-empty-message"),
]


@pytest.mark.parametrize("message, readings, expected", CASES)
def test_a_sent_message_is_judged_only_against_the_readings_that_answered_and_a_number_no_read_returned_is_a_finding(
        message: str, readings: list, expected: tuple) -> None:
    """The rules found, in reading order, are the hand-derived ones."""
    assert tuple(finding.rule for finding in check(message, readings)) == expected
