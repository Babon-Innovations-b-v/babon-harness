"""Read-only `gh_pr_view` tool, view a PR's body, state + recent comments.

Backed by `gh` CLI (already in the image; auth via `GH_TOKEN`). Mirrors
`gh_issue_view`'s subprocess style. Output is cut by
`text.truncate_keep_tail`, oldest comments first. Tool-module grammar: `NAME`, `DEFINITION`, `execute`.

TWO CALLS ON PURPOSE. Without a TTY, `gh pr view --comments` prints the
comment blocks INSTEAD of the overview, not in addition to it, so the
single `--comments` call this tool used to make handed the model comments
with no title, state, author, labels or body. State is the whole point
here: deploy correlation asks whether a PR is open, closed or merged, and
that was the one word being dropped (e2e case `tools-gh-pr-view-live`;
same root cause as `gh_issue_view`). The
overview call therefore runs first and the comments call is appended to it.

FAILURE POLICY: a non-zero `gh` exit returns `result.failed` carrying its
stderr, so the model reads FAILED rather than an OK over an error (a failed
view read as OK could be reported as a missing issue);
subprocess timeouts propagate to the registry's defended Tier-2 catch. A failing comments call keeps the
overview and says the comments could not be read, because a silently
dropped half would read as "no comments".
"""
from __future__ import annotations

from apps.assistant.shared.project import GITHUB_REPO

import subprocess
from typing import Any

from apps.assistant.core.tools.meta import result
from apps.assistant.core.tools.meta.text import truncate_keep_tail

NAME = "gh_pr_view"

_REPO = GITHUB_REPO

DEFINITION: dict[str, Any] = {
    "name": NAME,
    "description": "A GitHub pull request's body, state and last few comments.",
    "input_schema": {
        "type": "object",
        "properties": {
            "pr_number": {
                "type": "integer",
                "description": "PR number in the project repository.",
            },
        },
        "required": ["pr_number"],
    },
}


def _view(pr_number: int, extra_args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run one `gh pr view` invocation against the repo."""
    return subprocess.run(
        ["gh", "pr", "view", str(pr_number), "--repo", _REPO, *extra_args],
        capture_output=True,
        text=True,
        timeout=20,
    )


def execute(tool_input: dict[str, Any]) -> result.ToolResult | str:
    pr_number = int(tool_input["pr_number"])
    overview = _view(pr_number, [])
    if overview.returncode != 0:
        return result.failed(NAME, f"gh pr view failed (rc={overview.returncode}): {overview.stderr.strip()}")
    comments = _view(pr_number, ["--comments"])
    if comments.returncode != 0:
        tail = f"comments could not be read (rc={comments.returncode}): {comments.stderr.strip()}"
    else:
        # A PR with no comments prints nothing at all, so say so: an empty tail
        # would otherwise be indistinguishable from a comments call that
        # returned nothing for another reason.
        tail = comments.stdout.strip() or "no comments on this pull request"
    return truncate_keep_tail(f"{overview.stdout.rstrip()}\n\n--- comments ---\n", tail)
