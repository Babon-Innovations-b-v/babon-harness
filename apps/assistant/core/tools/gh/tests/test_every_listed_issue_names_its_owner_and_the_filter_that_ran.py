"""Every issue the assistant lists names its owner, and the listing names its filter.

WHAT IT PINS. `gh_issue_list.execute` with `subprocess.run` replaced, and
`changes.digest_since` with `changes._run_gh` replaced: each issue row carries
`owner: <login>`, an issue with nobody on it says `owner: unassigned` in
words, the gh listing opens with the filter that ran, and a gh failure is a
FAILED result rather than text the seam would label OK.

WHY IT EXISTS. Plain `gh issue list` prints no assignee column and the change
feed asked gh for none, so a missing column read as "nobody owns this": an
issue out of an `assignee:alex-example` search could be called unowned, and a
teammate's issue could land in the owner's list.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The gh JSON
payload is written by hand in the shape `gh issue list --json` documents
(`assignees` is a list of objects with a `login`), so the expected owner of
each row is read straight off the fixture.
"""
from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest

from apps.assistant.core import changes
from apps.assistant.core.tools.gh import gh_issue_list
from apps.assistant.core.tools.meta import result

_ISSUES = [
    {"number": 82, "title": "Deploy phase metrics", "state": "OPEN",
     "updatedAt": "2026-09-07T09:00:00Z", "labels": [{"name": "enhancement"}],
     "assignees": [{"login": "alex-example"}]},
    {"number": 1, "title": "Write the onboarding guide", "state": "OPEN",
     "updatedAt": "2026-09-09T09:00:00Z", "labels": [],
     "assignees": [{"login": "sam-example"}]},
    {"number": 2, "title": "Nobody on this", "state": "OPEN",
     "updatedAt": "2026-09-10T09:00:00Z", "labels": [], "assignees": []},
    {"number": 91, "title": "Done already", "state": "CLOSED",
     "updatedAt": "2026-09-11T09:00:00Z", "labels": [], "assignees": [{"login": "sam-example"}]},
]


def _fake_gh_payload(argv: list[str]) -> str:
    """What gh would print for `--json <fields>`: only the asked-for fields."""
    fields = argv[argv.index("--json") + 1].split(",") if "--json" in argv else []
    return json.dumps([{field: issue[field] for field in fields if field in issue} for issue in _ISSUES])


def _row_for(text: str, number: int) -> str:
    return next(line for line in text.splitlines() if f"#{number} " in line)


def test_the_issue_list_names_every_owner_and_its_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each row says whose it is; the first line says which search ran."""
    def _run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, _fake_gh_payload(argv), "")

    monkeypatch.setattr(gh_issue_list.subprocess, "run", _run)
    outcome = gh_issue_list.execute({"search": "assignee:alex-example state:open"})
    assert outcome.status == result.OK
    assert outcome.data.splitlines()[0] == "filter: search 'assignee:alex-example state:open' (state open)"
    assert "owner: alex-example" in _row_for(outcome.data, 82)
    assert "owner: sam-example" in _row_for(outcome.data, 1)
    assert "owner: unassigned" in _row_for(outcome.data, 2)


def test_every_listed_issue_says_whether_it_is_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """With state all, each row still says OPEN or CLOSED: the filter line
    cannot, and plain `gh issue list` printed the state on every row."""
    def _run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, _fake_gh_payload(argv), "")

    monkeypatch.setattr(gh_issue_list.subprocess, "run", _run)
    outcome = gh_issue_list.execute({"state": "all"})
    assert "#82 [OPEN] " in _row_for(outcome.data, 82)
    assert "#91 [CLOSED] " in _row_for(outcome.data, 91)


def test_a_failed_listing_is_failed_not_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """gh exiting non-zero comes back FAILED with its stderr."""
    def _run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 1, "", "HTTP 502")

    monkeypatch.setattr(gh_issue_list.subprocess, "run", _run)
    outcome = gh_issue_list.execute({})
    assert outcome.status == result.FAILED
    assert "HTTP 502" in outcome.error


def test_the_change_feed_names_every_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    """The digest a report grounds on carries the owner on each issue line."""
    def _gh(args: list[str]) -> tuple[int, str, str]:
        if args[0] == "api":
            return 0, "", ""
        return 0, _fake_gh_payload(args), ""

    monkeypatch.setattr(changes, "_run_gh", _gh)
    digest = changes.digest_since("2026-09-07T06:00:00Z")
    assert "owner: alex-example" in _row_for(digest, 82)
    assert "owner: sam-example" in _row_for(digest, 1)
    assert "owner: unassigned" in _row_for(digest, 2)
