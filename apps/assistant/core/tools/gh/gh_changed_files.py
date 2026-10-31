"""Read-only `gh_changed_files` tool, what a commit (or a deploy range)
actually touched (from the assistant's own self-assessment:
"I see a commit landed, I don't know what it touched").

The assistant already sees commit subjects (`gh_commits`) but not the files, so it
could time-correlate a deploy with a breakage yet not point at the likely
file/service. This closes that: given one commit it lists that commit's
changed files; given two refs (base..head, e.g. the previous deployed SHA
and the current one) it lists everything the deploy changed. Turns "a
deploy landed around then" into "that deploy touched
apps/assistant/gates/app.py".

Backed by the `gh api compare/commits` endpoints via the read-only
`GH_TOKEN` (same auth as the other gh read tools). Output truncated by the
shared 8 KiB cap. Tool-module grammar: `NAME`, `DEFINITION`, `execute`.

FAILURE POLICY: a non-zero `gh` exit returns its stderr as the tool result
(the LLM reacts); the registry's Tier-2 catch covers subprocess faults.
"""
from __future__ import annotations

from apps.assistant.shared.project import GITHUB_REPO

import subprocess
from typing import Any

from apps.assistant.core.tools.meta.text import truncate

NAME = "gh_changed_files"
_REPO = GITHUB_REPO
_TIMEOUT_S = 20

DEFINITION: dict[str, Any] = {
    "name": NAME,
    "description": (
        "The files one commit changed (`ref`), or everything between two SHAs "
        "(`base` and `head`), to tie a problem to the deploy that touched it."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "ref": {
                "type": "string",
                "description": "Commit SHA or branch.",
            },
            "base": {"type": "string", "description": "Range start SHA (with head)."},
            "head": {"type": "string", "description": "Range end SHA (with base)."},
        },
    },
}


def _gh_json(path: str, jq: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["gh", "api", f"repos/{_REPO}/{path}", "--jq", jq],
        capture_output=True, text=True, timeout=_TIMEOUT_S, check=False,
    )


def execute(tool_input: dict[str, Any]) -> str:
    base = str(tool_input.get("base", "")).strip()
    head = str(tool_input.get("head", "")).strip()
    ref = str(tool_input.get("ref", "")).strip()

    if base and head:
        result = _gh_json(
            f"compare/{base}...{head}",
            '.files[] | "\\(.status)\\t\\(.filename)"',
        )
        label = f"{base[:8]}..{head[:8]}"
    elif ref:
        result = _gh_json(
            f"commits/{ref}",
            '.files[] | "\\(.status)\\t\\(.filename)"',
        )
        label = ref[:8]
    else:
        return "need either 'ref' (one commit) or both 'base' and 'head' (a range)"

    if result.returncode != 0:
        return f"gh changed-files failed: {result.stderr[:300]}"
    body = result.stdout.strip() or "(no file changes)"
    return truncate(f"changed files ({label}):\n{body}")
