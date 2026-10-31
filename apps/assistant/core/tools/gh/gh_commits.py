"""Read-only `gh_commits` tool, recent commits on a branch.

Backed by `gh api` (already in the image; auth via `GH_TOKEN`). Mirrors
`gh_issue_view`'s subprocess style, using the REST commits endpoint with
a jq projection so the LLM sees sha/author/message without the full JSON
blob. Output is truncated by `text.truncate`. Tool-module grammar:
`NAME`, `DEFINITION`, `execute`.

FAILURE POLICY: a non-zero `gh` exit returns `result.failed` carrying its
stderr, so the model reads FAILED rather than an OK over an error (a failed
view read as OK could be reported as a missing issue);
subprocess timeouts propagate to the registry's defended Tier-2 catch.
"""
from __future__ import annotations

from apps.assistant.shared.project import GITHUB_REPO

import subprocess
from typing import Any

from apps.assistant.core.tools.meta import result
from apps.assistant.core.tools.meta.text import truncate

NAME = "gh_commits"

# Hard cap on listed commits, keeps one call bounded.
_MAX_LIMIT = 30


DEFINITION: dict[str, Any] = {
    "name": NAME,
    "description": (
        "Recent commits on a branch of the project repository (sha, author, "
        "date, first line). Push to main is the deploy."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "branch": {
                "type": "string",
                "description": "Default 'main'.",
                "default": "main",
            },
            "limit": {
                "type": "integer",
                "description": "Max 30, default 10.",
                "default": 10,
            },
        },
        "required": [],
    },
}


def execute(tool_input: dict[str, Any]) -> result.ToolResult | str:
    branch = str(tool_input.get("branch", "main"))
    limit = min(int(tool_input.get("limit", 10)), _MAX_LIMIT)
    completed = subprocess.run(
        [
            "gh",
            "api",
            f"repos/{GITHUB_REPO}/commits?sha={branch}&per_page={limit}",
            "--jq",
            ".[] | {sha: .sha[0:8], author: .commit.author.name, "
            "date: .commit.author.date, message: (.commit.message | split(\"\\n\")[0])}",
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if completed.returncode != 0:
        return result.failed(NAME, f"gh commits failed (rc={completed.returncode}): {completed.stderr.strip()}")
    return truncate(completed.stdout)
