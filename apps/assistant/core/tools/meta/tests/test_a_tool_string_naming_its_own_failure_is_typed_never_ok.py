"""A plain string in which a tool names its own failure is never typed OK.

WHAT IT PINS. `result.coerce` and `result.render`, the seam every unmigrated
tool's plain-string answer passes through on its way to the model and to the
MCP door's `isError`. A string opening "<tool name> failed" is FAILED, one
opening "<tool name> tool not configured" is UNAVAILABLE, and an OK answer
that merely mentions a failure stays OK. An empty OK answer is rendered as
"matched nothing", never as a finding that all is well.

HOW THE EXPECTED ANSWER IS DERIVED WITHOUT THE CODE UNDER TEST. The failure
strings are copied from the tools that emit them on main ("gh issue list
failed (rc=1): ...", "loki query failed: HTTP 502", "db_query tool not
configured (...)"), and the expected status is what each string says about
itself in plain English: the tool did not get an answer.
"""
from __future__ import annotations

import pytest

from apps.assistant.core.tools.meta import result


@pytest.mark.parametrize(
    ("tool", "text", "status"),
    [
        ("gh_issue_list", "gh issue list failed (rc=1): HTTP 502", result.FAILED),
        ("loki_query", "loki query failed: HTTP 502, bad gateway", result.FAILED),
        ("agenda_view", "agenda_view failed: HTTP 500: oops", result.FAILED),
        ("db_query", "db_query tool not configured (OPENCLAW_DB_RO_URL unset)", result.UNAVAILABLE),
        ("deploy_status", "last deploy failed at 10:02, rolled back", result.OK),
        ("gh_issue_list", "#12 OPEN fix: gh issue list failed for Sam", result.OK),
    ],
)
def test_a_tool_string_naming_its_own_failure_is_typed_never_ok(tool, text, status) -> None:
    """The status follows what the string says about the tool itself."""
    assert result.coerce(tool, text).status == status


def test_a_failure_string_renders_as_not_evidence() -> None:
    """What the model reads opens with FAILED, never OK."""
    rendered = result.render(result.coerce("gh_issue_view", "gh issue view failed (rc=1): Could not resolve to an Issue"))
    assert rendered.startswith("FAILED [gh_issue_view @ ")


def test_an_empty_answer_is_not_rendered_as_a_health_statement() -> None:
    """Nothing matched says nothing about health or existence."""
    rendered = result.render(result.coerce("journal_read", ""))
    assert "genuinely" not in rendered
    assert "not a statement about health or existence" in rendered
