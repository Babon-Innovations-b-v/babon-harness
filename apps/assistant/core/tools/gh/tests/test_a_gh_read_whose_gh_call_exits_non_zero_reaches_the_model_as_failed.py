"""A gh read whose `gh` call exits non-zero answers with a typed failure.

WHAT IT PINS. `execute` of `gh_issue_view`, `gh_pr_view` and `gh_commits`, the
tool modules' public interface: when the `gh` subprocess exits non-zero, the
answer is a `ToolResult` with status FAILED carrying gh's stderr, and the
registry renders it to the model opening "FAILED [", never "OK [".

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. `gh` exits 1
with "Could not resolve to an Issue" on a lookup it could not make; that is
gh's own statement that no answer was obtained, so the only honest status is
FAILED. The stub reproduces that exit code and stderr verbatim.
"""
from __future__ import annotations

import subprocess

import pytest

from apps.assistant.core import tools
from apps.assistant.core.tools.gh import gh_commits, gh_issue_view, gh_pr_view
from apps.assistant.core.tools.meta import result

_STDERR = "GraphQL: Could not resolve to an Issue with the number of 38."


def _gh_refuses(*args, **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr=_STDERR)


@pytest.mark.parametrize(
    ("module", "tool_input"),
    [
        (gh_issue_view, {"issue_number": 38}),
        (gh_pr_view, {"pr_number": 38}),
        (gh_commits, {"branch": "main"}),
    ],
)
def test_a_gh_read_whose_gh_call_exits_non_zero_reaches_the_model_as_failed(
    monkeypatch, module, tool_input
) -> None:
    """The module answers FAILED with gh's stderr, and the model reads FAILED."""
    monkeypatch.setattr(module.subprocess, "run", _gh_refuses)
    answer = module.execute(tool_input)
    assert isinstance(answer, result.ToolResult)
    assert answer.status == result.FAILED
    assert _STDERR in answer.error
    assert tools.execute(module.NAME, tool_input).startswith(f"FAILED [{module.NAME} @ ")
