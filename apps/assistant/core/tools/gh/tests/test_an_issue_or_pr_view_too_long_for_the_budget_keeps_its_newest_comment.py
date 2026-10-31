"""An issue or PR view too long for the budget keeps its newest comment.

WHAT IT PINS. `execute` of `gh_issue_view` and `gh_pr_view`, the tool modules'
public interface: when the overview plus the comments run past the per-result
byte budget, the oldest comments are cut, the newest comment survives, the
overview's title survives, the cut is marked, and the answer stays inside the
budget.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. `gh ... view
--comments` prints comments oldest first, so the newest comment is the last
block of its stdout. The stub writes 40 comments of about 300 bytes each, far
past 8 KiB, and the last one carries a unique marker; that marker must appear,
the first comment's marker must not.
"""
from __future__ import annotations

import subprocess

import pytest

from apps.assistant.core.tools.gh import gh_issue_view, gh_pr_view

_TITLE = "title:\tOffice lease renewal"
_OLDEST = "COMMENT-0000-OLDEST"
_NEWEST = "COMMENT-0039-NEWEST request sent to the landlord on 28 Sep"


def _comments() -> str:
    blocks = [f"author:\talex-example\n{_OLDEST}\n" + "x" * 280]
    blocks += [f"author:\talex-example\ncomment {index}\n" + "y" * 280 for index in range(1, 39)]
    blocks.append(f"author:\talex-example\n{_NEWEST}\n")
    return "\n--\n".join(blocks)


def _gh(args, **kwargs) -> subprocess.CompletedProcess[str]:
    stdout = _comments() if "--comments" in args else f"{_TITLE}\nstate:\tOPEN\n\nbody text"
    return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout, stderr="")


@pytest.mark.parametrize(
    ("module", "tool_input"),
    [
        (gh_issue_view, {"issue_number": 38}),
        (gh_pr_view, {"pr_number": 38}),
    ],
)
def test_an_issue_or_pr_view_too_long_for_the_budget_keeps_its_newest_comment(
    monkeypatch, module, tool_input
) -> None:
    """The newest comment and the title survive, the oldest is cut, the cut is marked."""
    monkeypatch.setattr(module.subprocess, "run", _gh)
    answer = module.execute(tool_input)
    assert _NEWEST in answer
    assert _TITLE in answer
    assert _OLDEST not in answer
    assert "cut" in answer
    assert len(answer.encode("utf-8")) <= 8192
