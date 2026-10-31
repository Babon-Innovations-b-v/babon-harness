"""Read-only `gh_issue_list` tool, list recent open issues.

Backed by `gh` CLI (already in the image; auth via `GH_TOKEN`). Mirrors
`gh_issue_view`'s subprocess style. Output is truncated by
`text.truncate`. Tool-module grammar: `NAME`, `DEFINITION`, `execute`.

EVERY ROW NAMES ITS OWNER, and the result names the filter that ran.
Plain `gh issue list` prints no assignee column, so a model can read a
missing column as "nobody owns this", even straight out of an
`assignee:<login>` search. An empty assignee list is written
out as `owner: unassigned`, never left blank.

FAILURE POLICY: a non-zero `gh` exit is a FAILED result carrying its stderr
(the LLM reacts to it, and cannot mistake it for an empty list); subprocess
timeouts propagate to the registry's defended Tier-2 catch.
"""
from __future__ import annotations

from apps.assistant.shared.project import GITHUB_REPO, PEOPLE

import json
import subprocess
from typing import Any

from apps.assistant.core.changes import owner_label
from apps.assistant.core.tools.meta import result
from apps.assistant.core.tools.meta.text import truncate

NAME = "gh_issue_list"

# Hard cap on listed issues, keeps one call bounded.
_MAX_LIMIT = 30


DEFINITION: dict[str, Any] = {
    "name": NAME,
    "description": (
        "List issues in the project repository. A person's own work: search "
        "'assignee:<login> state:open'; where they are tagged: 'mentions:<login> "
        "state:open'; never 'involves:'."
        + (" Logins: " + ", ".join(f"{name}={login}" for name, login in PEOPLE.items()) + "." if PEOPLE else "")
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Max 30.",
                "default": 15,
            },
            "state": {
                "type": "string",
                "description": "Issue state.",
                "enum": ["open", "closed", "all"],
                "default": "open",
            },
            "assignee": {
                "type": "string",
                "description": "GitHub login.",
            },
            "search": {
                "type": "string",
                "description": "GitHub issue-search query; overrides assignee.",
            },
        },
        "required": [],
    },
}


_JSON_FIELDS = "number,state,title,labels,assignees,updatedAt"


def _row_line(row: dict[str, Any]) -> str:
    """One issue as `#N [STATE] title | owner: ... | labels: ... | updated ...`.

    The state rides on every row: with `state` all or a `state:` search the
    filter line cannot say which rows are open."""
    labels = ", ".join(str(label.get("name", "")) for label in row.get("labels") or [])
    return (
        f"#{row.get('number')} [{row.get('state', 'STATE UNKNOWN')}] {row.get('title', '')}"
        f" | {owner_label(row.get('assignees'))}"
        f" | labels: {labels or 'none'} | updated {row.get('updatedAt', '')}"
    )


def _filter_line(state: str, search: str, assignee: str) -> str:
    """Which filter the listing ran with, so the rows sit next to their query."""
    if search:
        return f"filter: search '{search}' (state {state})"
    if assignee:
        return f"filter: assignee '{assignee}' (state {state})"
    return f"filter: none (state {state}, most recent)"


def execute(tool_input: dict[str, Any]) -> result.ToolResult:
    limit = min(int(tool_input.get("limit", 15)), _MAX_LIMIT)
    state = str(tool_input.get("state", "open"))
    argv = [
        "gh", "issue", "list",
        "--repo", GITHUB_REPO,
        "--state", state,
        "--limit", str(limit),
    ]
    # A person's tasks: `search` (assignee:/mentions: query) wins,
    # else the `assignee` shortcut. Neither given = the plain recent list.
    search = str(tool_input.get("search", "")).strip()
    assignee = str(tool_input.get("assignee", "")).strip()
    if search:
        argv += ["--search", search]
    elif assignee:
        argv += ["--assignee", assignee]
    argv += ["--json", _JSON_FIELDS]
    completed = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if completed.returncode != 0:
        return result.failed(
            NAME, f"gh issue list failed (rc={completed.returncode}): {completed.stderr.strip()}"
        )
    try:
        rows = json.loads(completed.stdout or "[]") or []
    except json.JSONDecodeError:
        return result.failed(NAME, "gh issue list output was not JSON")
    lines = [_filter_line(state, search, assignee)]
    lines += [_row_line(row) for row in rows] or ["no issues matched this filter."]
    return result.ok(NAME, truncate("\n".join(lines)))
