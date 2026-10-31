#!/usr/bin/env python3
"""PostToolUse hook: keep the bible and the drawn set pointing at each other.

Fires after Edit/Write. If the touched file is docs/bible.md or anything in
docs/diagrams/, rerun docs/diagrams/tools/linkmap.py, which rewrites every
page's links.json from the ◈ markers in the bible plus the readable index at
docs/diagrams/tools/linkmap.md, and checks both directions: a box claimed by
no sentence or by two, a marker outside a section, a page that hangs under
nothing, a zoom-out that lands where the reader could not have come from.
Those errors surface to the model (exit 2) so they are fixed in the same
session; other files are ignored silently.

TWO THINGS IT DOES NOT DO.

It does not fail on `drifted_code`. That check reports a box whose code moved
and asks a PERSON to re-read the drawing, which is a judgement no hook can
make. Blocking on it blocks whoever edits the diagrams next, about somebody
else's commit, which is how a check comes to be scrolled past. Drift is printed
as a note and the edit stands. `linkmap.py --restamp <page#box> ...` is how the
boxes somebody actually read get recorded.

And it does not validate the shared checkout while you edit a worktree. Taking
the root from CLAUDE_PROJECT_DIR would tell a session working in
`.claude/worktrees/<slug>` about the OTHER tree's boxes, with its own edit
invisible, so the root is found by walking up from the edited file, which
answers correctly in a worktree and in the shared checkout alike.

It only rewrites the sidecars, it does not re-render the pages. linkmap.py
prints the pages whose links moved; those need docs/diagrams/tools/deliver.sh
before the popups match.
"""
import json
import os
import pathlib
import subprocess
import sys

#: What `drifted_code` writes, and nothing else does. Matched on the sentence
#: rather than on an exit code because linkmap answers 2 for every problem it
#: finds, and its exit code is a contract the diagram MCP also reads.
_DRIFT = "the code this box draws changed"


def _linkmap_for(edited: str) -> pathlib.Path | None:
    """The tool belonging to the tree the edited file is in.

    Walks up from the file, so a worktree gets its own copy and the shared
    checkout gets that one. Falls back to CLAUDE_PROJECT_DIR for a path that is
    not inside any tree holding the tool.
    """
    here = pathlib.Path(edited).resolve()
    for directory in (here, *here.parents):
        candidate = directory / "docs" / "diagrams" / "tools" / "linkmap.py"
        if candidate.exists():
            return candidate
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    fallback = pathlib.Path(root) / "docs" / "diagrams" / "tools" / "linkmap.py"
    return fallback if fallback.exists() else None


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    path = (payload.get("tool_input") or {}).get("file_path", "")
    if not path:
        return 0
    norm = path.replace("\\", "/")
    if not (norm.endswith("docs/bible.md") or "/docs/diagrams/" in norm or norm.startswith("docs/diagrams/")):
        return 0
    if norm.endswith("linkmap.md"):
        return 0
    tool = _linkmap_for(path)
    if tool is None:
        return 0
    result = subprocess.run(
        [sys.executable, str(tool)],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(tool.parents[3]),
    )
    if result.returncode == 0:
        return 0

    lines = [line for line in (result.stderr or "").splitlines() if line.strip()]
    blocking = [line for line in lines if _DRIFT not in line]
    if blocking:
        sys.stderr.write("\n".join(blocking) + "\n")
        return 2
    if lines:
        sys.stderr.write(
            f"linkmap: {len(lines)} drawn box(es) name code that has moved. "
            "Re-read the ones your change touched, then record it with "
            "`python3 docs/diagrams/tools/linkmap.py --restamp <page#box> ...`. "
            "Not blocking: most of these belong to somebody else's commit.\n"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
