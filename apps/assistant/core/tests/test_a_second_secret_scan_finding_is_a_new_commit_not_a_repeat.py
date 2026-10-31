"""Two secret-scan pings on two commits are two findings, and each page names
its commit.

WHAT IT PINS. `core.page_render`, through `licenses_aspect` and `render` over
every selection a batch licenses, fed by `core.ping_facts.bundle`. The pen
counts history by subject, and the scan sends one fixed subject once per
commit, so a second ping on that subject is always another commit. A page that
calls it "Second time on this subject" and names no commit makes two leaks
read as one.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The two rows are
two synthetic pen rows in the stored row shape: two commits,
1111111 and 2222222, the second paged as a repeat of the first. The history
stub says the subject was seen twice before. The
expected commits are read off each row's own `SHA:` line by eye. The control is
a gate-red page with the same history, which is a real repeat of one subject
and must keep both its escalation and its rule of printing no sha.
"""
from __future__ import annotations

import re

from apps.assistant.core import page_render, ping_facts

SUBJECT = "\U0001f6a8 [the project] auto-deploy: secret scan found a possible committed secret"
BODY = (
    "SHA: {sha}\n"
    "gitleaks reports findings in the new commits. Findings are redacted\n"
    "here; full pointers in the scan log on the VM.\n"
    "If real: rotate the secret FIRST, then scrub the history.\n\n"
    "gitleaks tail (redacted):\n"
    "\x1b[90m11:30AM\x1b[0m \x1b[33mWRN\x1b[0m \x1b[1mleaks found: 1\x1b[0m"
)
FIRST = {
    "id": 11,
    "subject": SUBJECT,
    "body": BODY.format(sha="1111111111aa1111111111aa1111111111aa1111"),
    "received_at": "2030-01-15T09:00:00+00:00",
    "facts": {"exit_code": "1", "blocks_deploy": "no"},
}
SECOND = {
    "id": 12,
    "subject": SUBJECT,
    "body": BODY.format(sha="2222222222bb2222222222bb2222222222bb2222"),
    "received_at": "2030-01-15T11:30:00+00:00",
    "facts": {"exit_code": "1", "blocks_deploy": "no"},
}
GATE_RED = {
    "id": 13,
    "subject": "\U0001f534 [the project] auto-deploy: verification gate RED",
    "body": "SHA: 0123456789abcdef0123456789abcdef01234567\nThe gate refused it.",
    "received_at": "2030-01-15T11:30:00+00:00",
}


def _seen_twice(_subject: str) -> dict:
    return {"seen_count": 2, "last_delivered_at": "2030-01-15T09:00:20+00:00"}


def _pages(row: dict) -> list[str]:
    """Every page the pen could send with `row` as the whole batch."""
    batch = ping_facts.bundle([row], history_of=_seen_twice)
    return [
        page_render.render(selection, batch, language=language)
        for language in ("en", "nl")
        for selection in page_render.every_selection(batch)
        if selection.verdict == "page"
    ]


def test_a_second_finding_is_not_called_a_repeat() -> None:
    (fact,) = ping_facts.bundle([SECOND], history_of=_seen_twice)
    assert not page_render.licenses_aspect(fact, "escalation")
    for page in _pages(SECOND):
        assert "time on this subject" not in page, page
        assert "keer over dit onderwerp" not in page, page


def test_each_finding_names_its_own_commit() -> None:
    for row, commit in ((FIRST, "1111111"), (SECOND, "2222222")):
        pages = _pages(row)
        assert pages
        for page in pages:
            assert f"Commit {commit}." in page, page


def test_a_gate_red_repeat_still_escalates_and_prints_no_sha() -> None:
    (fact,) = ping_facts.bundle([GATE_RED], history_of=_seen_twice)
    assert page_render.licenses_aspect(fact, "escalation")
    for page in _pages(GATE_RED):
        assert not re.search(r"\b[0-9a-f]{7,40}\b", page), page
