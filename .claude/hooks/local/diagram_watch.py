#!/usr/bin/env python3
"""Keep the drawn set honest about what this session built.

Two events, one job.

PostToolUse (Edit|Write): note which area of the tree a file belongs to, in
a small per-session file. Cheap, silent, no judgement.

Stop: read that note back and say which touched areas have no drawn page (their
own, or the group page that answers for them), and which have one that did not
move while the code did. It reminds and exits 0;
it never blocks, because a map that is wrong is worse than one that is
missing, and only the session knows whether the change was worth drawing.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

REPO = pathlib.Path(os.environ.get("CLAUDE_PROJECT_DIR", pathlib.Path.cwd()))
# What this hook reads is the build sidecars, not the served pages, so it looks
# in data/stack/: docs/diagrams/stack/ holds nothing but the delivered .html.
STACK_DATA = REPO / "docs" / "diagrams" / "data" / "stack"
STATE_DIR = REPO / ".claude" / "state"

#: The top-level directories that hold code a reader would expect to find
#: drawn. An area is the first two path segments under one of them, as in
#: ``apps/notulen`` or ``infra/auto-deploy``, and the page that answers for it is
#: named after the second segment (``notulen``), or a group page carrying the
#: ``group-`` prefix of the first (``group-apps``). docs and business are not
#: code and are never counted.
AREA_ROOTS = ("apps", "infra", "lib", "tools")


def state_path() -> pathlib.Path:
    session = os.environ.get("CLAUDE_SESSION_ID", "session")
    return STATE_DIR / f"diagram-touched-{session}.json"


def area_for(path: str) -> str | None:
    """``<root>/<name>`` for a file under one of the area roots, else None."""
    parts = pathlib.PurePosixPath(path).parts
    if len(parts) < 3 or parts[0] not in AREA_ROOTS:
        return None
    return f"{parts[0]}/{parts[1]}"


def pages_for(area: str) -> list[str]:
    """The pages that may answer for an area: its own, then its group's."""
    root, name = area.split("/", 1)
    return [name, f"group-{root}"]


def record(payload: dict) -> int:
    path = (payload.get("tool_input") or {}).get("file_path", "")
    if not path:
        return 0
    try:
        rel = str(pathlib.Path(path).resolve().relative_to(REPO.resolve()))
    except (ValueError, OSError):
        return 0
    area = area_for(rel)
    if not area:
        return 0
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    store = state_path()
    touched = json.loads(store.read_text()) if store.exists() else {}
    touched.setdefault(area, [])
    if rel not in touched[area]:
        touched[area].append(rel)
    store.write_text(json.dumps(touched, indent=1, sort_keys=True) + "\n")
    return 0


def map_did_not_move(page: str) -> bool:
    """True when this page has no uncommitted change while the code has one.

    The signal is the working tree, not the branch history: a page whose
    sidecar is edited in this session shows up in `git status`, so a clean
    sidecar next to touched code is what "the code moved and the map did not"
    means here. A map redrawn and already committed earlier in the session
    therefore still reads as stale, which is a reminder too many rather than a
    reminder too few.
    """
    source = STACK_DATA / f"{page}.notes.json"
    if not source.exists():
        return True
    head = subprocess.run(
        ["git", "-C", str(REPO), "status", "--porcelain", "--", str(source)],
        capture_output=True, text=True)
    return not head.stdout.strip()


def report() -> int:
    store = state_path()
    if not store.exists():
        return 0
    touched = json.loads(store.read_text())
    store.unlink(missing_ok=True)
    missing, stale = [], []
    for area, files in touched.items():
        pages = pages_for(area)
        drawn = [p for p in pages if (STACK_DATA / f"{p}.architecture.json").exists()]
        if not drawn:
            missing.append(area)
        elif all(map_did_not_move(p) for p in drawn):
            stale.append(f"{area} ({', '.join(drawn[:3])})")
    if not missing and not stale:
        return 0
    lines = ["A module is drawn while it is built, and explained in the bible in the same pass."]
    if missing:
        lines.append(f"No map yet for: {', '.join(sorted(missing))}.")
    if stale:
        lines.append(f"Code moved but the map did not: {', '.join(sorted(stale))}.")
    lines.append("Draw it with the diagram MCP (draw_module) in the design system of "
                 "docs/diagrams/tools/REDRAW-BRIEF.md, write the bible section so every box is "
                 "claimed by one piece of text carrying its ◈ marker, run docs/diagrams/tools/linkmap.py, "
                 "and link the page only when the work needs a human eye.")
    print(" ".join(lines), file=sys.stderr)
    return 0


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    event = payload.get("hook_event_name", "")
    if event == "PostToolUse":
        return record(payload)
    if event == "Stop":
        return report()
    return 0


if __name__ == "__main__":
    sys.exit(main())
