"""The subject line, and the one number the metric needs out of the report.

The report itself is rendered pod-side by `core/claim_audit/render.py`, which
is where it belongs: the rules live there and so does the wording. What is left
out here is the envelope, plus one reading back of the coverage line so the
metric can carry it.

FAILURE POLICY: pure. A coverage line it cannot parse answers 0, because a
metric guessing high would raise an alarm about the audit rather than about
The assistant.
"""
from __future__ import annotations

from apps.assistant.shared.name import ASSISTANT_NAME

from apps.assistant.watch.claim_audit.fetch import Audit

# The words `core/claim_audit/render._coverage` opens its line with. Read
# rather than recomputed, because the container holds the window and this side does
# not; a rename there makes this answer 0, which is the safe direction.
_COVERAGE_MARK = " message(s) had no readings recorded"


def subject(audit: Audit) -> str:
    """The Talk subject: the count first, because that is the whole headline.

    An empty window says so in words instead. "0 unsupported claim(s) in 0
    message(s)" reads as a good week at a glance, and a week with no messages in
    it is the opposite: the morning brief sends Monday to Friday whatever
    happens, so zero means nothing was recorded rather than nothing was said.
    """
    if not audit.messages:
        return f"{ASSISTANT_NAME} claim audit: no messages were recorded in the whole window"
    return (
        f"{ASSISTANT_NAME} claim audit: {audit.findings} unsupported claim(s) in "
        f"{audit.messages} message(s)"
    )


def unbacked_count(report: str) -> int:
    """How many messages in the window had no readings behind them.

    Parsed off the coverage line rather than recomputed, since only the container
    saw the rows. A line that cannot be read answers 0.
    """
    for line in report.splitlines():
        if _COVERAGE_MARK not in line:
            continue
        first = line.strip().split(" ", 1)[0]
        if first.isdigit():
            return int(first)
    return 0
