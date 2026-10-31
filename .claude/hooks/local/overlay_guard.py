#!/usr/bin/env python3
"""PreToolUse guard: an overlay does not grow past its budget silently.

The rule (root CLAUDE.md): an overlay says what someone must not
get wrong in its directory and what will bite them; everything else is history,
and git already holds history. The budget is 500 words per ``CLAUDE.md``
overlay; one that earns more opens with a line starting ``Budget:`` saying why.

This guard blocks a ``Write`` or ``Edit`` that leaves an overlay over the
budget with MORE words than it had and no ``Budget:`` line. Shrinking is always
allowed, and so is any edit that keeps the file at or under budget, so a
session trimming a bloated overlay is never in its way. The repo-root
``CLAUDE.md`` is project instructions rather than an overlay and is not
covered; neither is anything outside the repo.

FAILURE POLICY: fail-open. Any parse error, unknown shape or unrelated call
exits 0 (allow). Exit 2 + stderr is the only block path (the harness feeds
stderr back to the model as the block reason). ``HARNESS_OVERLAY_GUARD=0``
disarms it, for a human at a terminal.
"""

import json
import os
import pathlib
import re
import sys

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

BUDGET_WORDS = 500

#: A line opening with "Budget:" (optionally bolded) is the written reason the
#: file earns more than the budget. Its presence is the whole exemption.
_BUDGET_LINE = re.compile(r"^\s*(\*\*)?budget:", re.IGNORECASE | re.MULTILINE)

_MESSAGE = (
    "Blocked: this would grow {path} to {new} words; the overlay budget is "
    f"{BUDGET_WORDS} (root CLAUDE.md).\n"
    "An overlay says what someone must not get wrong in its directory and what "
    "will bite them; everything else is history, and git already holds history.\n"
    "Either cut instead of adding, or, when the file genuinely earns more, add "
    "a line starting 'Budget:' saying why. Shrinking is always allowed."
)


def _overlay_path(raw: str) -> pathlib.Path | None:
    """The resolved path when `raw` is a per-area CLAUDE.md inside the repo."""
    if not raw:
        return None
    candidate = pathlib.Path(str(raw).strip())
    if not candidate.is_absolute():
        candidate = _REPO_ROOT / candidate
    try:
        resolved = candidate.resolve()
        resolved.relative_to(_REPO_ROOT)
    except (ValueError, OSError):
        return None
    if resolved.name != "CLAUDE.md":
        return None
    if resolved.parent == _REPO_ROOT:
        return None  # the root file is project instructions, not an overlay
    return resolved


def _resulting_content(tool: str, tool_input: dict, current: str) -> str | None:
    """What the file would hold after the call, or None when that is unknowable."""
    if tool == "Write":
        return str(tool_input.get("content", ""))
    if tool == "Edit":
        old = str(tool_input.get("old_string", ""))
        new = str(tool_input.get("new_string", ""))
        if not old or old not in current:
            return None  # the tool itself will refuse; nothing to judge
        if tool_input.get("replace_all"):
            return current.replace(old, new)
        return current.replace(old, new, 1)
    return None


def main() -> int:
    if os.environ.get("HARNESS_OVERLAY_GUARD", "1") == "0":
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}
    overlay = _overlay_path(tool_input.get("file_path", ""))
    if overlay is None:
        return 0

    try:
        current = overlay.read_text(encoding="utf-8") if overlay.exists() else ""
        result = _resulting_content(tool, tool_input, current)
        if result is None:
            return 0
        new_words = len(result.split())
        old_words = len(current.split())
        if (
            new_words > BUDGET_WORDS
            and new_words > old_words
            and not _BUDGET_LINE.search(result)
        ):
            rel = overlay.relative_to(_REPO_ROOT)
            print(_MESSAGE.format(path=rel, new=new_words), file=sys.stderr)
            return 2
    except Exception:
        return 0  # fail-open
    return 0


if __name__ == "__main__":
    sys.exit(main())
