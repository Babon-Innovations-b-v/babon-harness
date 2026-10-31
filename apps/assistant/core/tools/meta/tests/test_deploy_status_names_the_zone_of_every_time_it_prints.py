"""deploy_status names the zone of every time it prints.

WHAT IT PINS. `deploy_status.execute`, at its public seam, with `gh` answered
by a stand-in that returns commit statuses the way the GitHub API does: every
time in the answer is ISO UTC ending in Z.

WHY IT EXISTS. A time printed without its zone is read as local time by
whoever reads the brief, so a deploy at 18:11 UTC would read as 18:11
local, hours off.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The stamps are
written by hand in GitHub's own UTC spelling, so the answer must hold
"2026-10-14T18:11:29Z" and "2026-10-07T16:31:50Z", and no clock time without a
zone after it.
"""
from __future__ import annotations

import json
import re

import pytest

from apps.assistant.core.tools.meta import deploy_status

_STATUSES = {
    "7a7a7a7a7aaa": [
        {"context": "vm/deploy", "state": "success", "updated_at": "2026-10-14T18:11:29Z"},
        {"context": "vm/gate", "state": "success", "updated_at": "2026-10-14T18:05:00Z"},
    ],
    "fedcba9876bb": [
        {"context": "vm/boot", "state": "failure", "updated_at": "2026-10-07T16:31:50Z"},
        {"context": "vm/gate", "state": "success", "updated_at": "2026-10-07T16:20:00Z"},
    ],
}
_CLOCK_RE = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(Z|[+-]\d{2}:\d{2})?")


def _fake_gh(args: list[str]) -> str | None:
    path = args[1]
    if "/commits?" in path:
        return "\n".join(_STATUSES)
    sha = path.split("/commits/")[1].split("/")[0]
    return json.dumps(_STATUSES[sha])


@pytest.fixture()
def answer(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(deploy_status, "_gh", _fake_gh)
    monkeypatch.setattr(
        deploy_status, "_pending_vs_main",
        lambda sha: deploy_status.PendingVsMain("up to date with main (7a7a7a7a7a)", 0),
    )
    return deploy_status.execute({})


def test_every_time_printed_carries_its_zone(answer: str) -> None:
    zones = _CLOCK_RE.findall(answer)
    assert zones, f"no time in the answer at all: {answer}"
    assert all(zones), (
        f"a time went out without its zone, which a reader takes as local: {answer}"
    )


def test_the_real_stamps_are_there(answer: str) -> None:
    assert "last success 2026-10-14T18:11:29Z" in answer, answer
    assert "2026-10-07T16:31:50Z deploy_failed vm/boot" in answer, answer
