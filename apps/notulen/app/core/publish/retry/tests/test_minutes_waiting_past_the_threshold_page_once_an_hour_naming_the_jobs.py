"""Minutes waiting past the threshold page once an hour, naming the jobs.

WHAT IT PINS. `publish.retry`: `stuck_committing_ids` picks the jobs whose
markdown has waited longer than fifteen minutes for its commit, and
`alert_stuck_committing` pages about them at most once an hour, naming them.
The clock is passed in and the page goes to a recorder.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The waits are
made-up offsets from one fixed instant, judged by hand against the stated
threshold of 900 seconds (exactly 900 is not past it). The pages are counted
from the stated throttle of 3,600 seconds between two pages.

ONE FUNCTION. This module's one test. A new check is a parametrized case of
it, never a second function.

WHAT IT WAS PROVED AGAINST. The break in this test's register row drops the
throttle, so the case paging twice inside an hour sends two pages.

GUARDS. One test per module (#1210), 2026-11-05.
"""
from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone

import pytest

stuck = importlib.import_module("apps.notulen.app.core.publish.retry.stuck_commits")
alert = importlib.import_module("apps.notulen.app.core.publish.retry.alert_stuck_committing")

AT = datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc)
ROWS = [
    ("job-a", AT - timedelta(seconds=901)),
    ("job-b", AT - timedelta(seconds=900)),
    ("job-c", None),
    ("job-d", AT - timedelta(hours=30)),
]

CASES = [
    pytest.param("stuck", None, ["job-a", "job-d"], id="only-past-the-threshold"),
    pytest.param("pages", (0.0,), 1, id="one-page"),
    pytest.param("pages", (0.0, 1800.0), 1, id="a-second-inside-the-hour-is-held"),
    pytest.param("pages", (0.0, 3600.0), 2, id="an-hour-later-pages-again"),
    pytest.param("names", (0.0,), True, id="the-page-names-the-jobs"),
]


@pytest.mark.parametrize("ask, ticks, expected", CASES)
def test_minutes_waiting_past_the_threshold_page_once_an_hour_naming_the_jobs(
        ask: str, ticks: tuple | None, expected: object, monkeypatch: pytest.MonkeyPatch) -> None:
    """The stuck jobs, the page count or the page text is the hand-derived answer."""
    if ask == "stuck":
        assert stuck.stuck_committing_ids(ROWS, AT) == expected
        return
    monkeypatch.setattr(alert, "_last_stuck_commit_alert_ts", -10_000.0)
    pages: list[tuple[str, str]] = []
    for tick in ticks:
        alert.alert_stuck_committing(
            ["job-a", "job-d"], notifier=lambda subject, body: pages.append((subject, body)),
            now=lambda tick=tick: 1_000_000.0 + tick,
        )
    seen = len(pages) if ask == "pages" else "Jobs: job-a, job-d" in pages[0][1]
    assert seen == expected
