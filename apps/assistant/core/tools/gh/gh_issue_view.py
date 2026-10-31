"""Read-only `gh_issue_view` tool, view an issue body + recent
comments.

Backed by `gh` CLI which is already in the image (added in slice 2).
Auth via `GH_TOKEN`, which `apps/assistant/compose.yml` sets from
`GITHUB_ASSISTANT_TOKEN` in the vault. Output is cut by `text.truncate_keep_tail`, oldest comments first,
so the newest comment always survives. Tool-module grammar: `NAME`,
`DEFINITION`, `execute`.

TWO CALLS ON PURPOSE. Without a TTY, `gh issue view --comments` prints
the comment blocks INSTEAD of the overview, not in addition to it, so
the single `--comments` call this tool used to make handed the model
comments with no title, state, labels, assignees or body. The assistant read
issues half-blind that way: it could see what people said about an
issue but not what the issue was, which is the opposite of what this
tool's own description promises (e2e case `tools-gh-issue-view-live`). The overview call therefore runs first and the comments
call is appended to it.

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

NAME = "gh_issue_view"

_REPO = GITHUB_REPO

DEFINITION: dict[str, Any] = {
    "name": NAME,
    "description": "A GitHub issue's body and last few comments.",
    "input_schema": {
        "type": "object",
        "properties": {
            "issue_number": {
                "type": "integer",
                "description": "Issue number in the project repository.",
            },
        },
        "required": ["issue_number"],
    },
}


def _view(issue_number: int, extra_args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run one `gh issue view` invocation against the repo."""
    return subprocess.run(
        ["gh", "issue", "view", str(issue_number), "--repo", _REPO, *extra_args],
        capture_output=True,
        text=True,
        timeout=20,
    )


def execute(tool_input: dict[str, Any]) -> result.ToolResult | str:
    issue_number = int(tool_input["issue_number"])
    overview = _view(issue_number, [])
    if overview.returncode != 0:
        return result.failed(NAME, f"gh issue view failed (rc={overview.returncode}): {overview.stderr.strip()}")
    comments = _view(issue_number, ["--comments"])
    if comments.returncode != 0:
        tail = f"comments could not be read (rc={comments.returncode}): {comments.stderr.strip()}"
    else:
        # An issue with no comments prints nothing at all, so say so: an empty
        # tail would otherwise be indistinguishable from a comments call that
        # returned nothing for another reason.
        tail = comments.stdout.strip() or "no comments on this issue"
    return truncate_keep_tail(f"{overview.stdout.rstrip()}\n\n--- comments ---\n", tail)
