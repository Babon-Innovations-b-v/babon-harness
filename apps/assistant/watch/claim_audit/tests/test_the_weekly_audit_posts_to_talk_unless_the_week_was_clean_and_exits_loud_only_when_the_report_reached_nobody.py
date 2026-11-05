"""The weekly audit posts to Talk unless the week was clean, and exits loud only when the report reached nobody.

WHAT IT PINS. `watch.claim_audit.watch.main`, the timer's one tick: it fetches
the week's audit, publishes the metric, stays quiet on a clean week, posts to
Talk a week with findings or with no messages at all (an empty week is never a
clean one), and exits 1 only when a post that had to land did not. The fetch,
the Talk post and the textfile directory are replaced by recorders and a
scratch directory.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. Each audit is
made up here, and the subject is written out from its counts in the words the
module promises; the unbacked count is read by hand off the report's coverage
line, "3 message(s) had no readings recorded".

ONE FUNCTION. This module's one test. A new check is a parametrized case of
it, never a second function.

WHAT IT WAS PROVED AGAINST. The break in this test's register row treats a week
with no findings as clean whether or not anything was said, so the empty week
is never posted.

GUARDS. One test per module (#1210), 2026-11-05.
"""
from __future__ import annotations

import importlib

import pytest

from apps.assistant.shared.name import ASSISTANT_NAME

watch = importlib.import_module("apps.assistant.watch.claim_audit.watch")
fetch = importlib.import_module("apps.assistant.watch.claim_audit.fetch")

REPORT = "Claim audit\n3 message(s) had no readings recorded beside them.\n"

CASES = [
    pytest.param(fetch.Audit(messages=12, findings=0, report=REPORT), True, (0, [], 3),
                 id="a-clean-week-posts-nothing"),
    pytest.param(fetch.Audit(messages=12, findings=2, report=REPORT), True,
                 (0, [f"{ASSISTANT_NAME} claim audit: 2 unsupported claim(s) in 12 message(s)"], 3),
                 id="findings-are-posted-count-first"),
    pytest.param(fetch.Audit(messages=0, findings=0, report="No messages recorded."), True,
                 (0, [f"{ASSISTANT_NAME} claim audit: no messages were recorded in the whole window"], 0),
                 id="an-empty-week-is-never-clean"),
    pytest.param(fetch.Audit(messages=12, findings=2, report=REPORT), False,
                 (1, [f"{ASSISTANT_NAME} claim audit: 2 unsupported claim(s) in 12 message(s)"], 3),
                 id="a-report-that-reached-nobody-exits-loud"),
]


@pytest.mark.parametrize("audit, talk_lands, expected", CASES)
def test_the_weekly_audit_posts_to_talk_unless_the_week_was_clean_and_exits_loud_only_when_the_report_reached_nobody(
        audit, talk_lands: bool, expected: tuple, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """(exit code, Talk subjects posted, unbacked count in the metric) is the hand-written one."""
    posted: list[str] = []
    monkeypatch.setattr(watch.fetch, "fetch", lambda secret: audit)
    monkeypatch.setattr(watch, "_post_to_talk", lambda subject, body: posted.append(subject) or talk_lands)
    monkeypatch.setenv("OPENCLAW_CLAIM_AUDIT_TEXTFILE_DIR", str(tmp_path))
    code = watch.main()
    metric = (tmp_path / "openclaw_claim_audit.prom").read_text()
    unbacked = next(int(line.split()[1]) for line in metric.splitlines()
                    if line.startswith("harness_claim_audit_unbacked_messages "))
    assert (code, posted, unbacked) == expected
