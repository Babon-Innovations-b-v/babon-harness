#!/usr/bin/env python3
"""SessionStart hook: tell a session when work from this repo is sitting in a hand-back.

WHY THIS EXISTS. When the deploy gate rejects a commit and the eject is armed
(`EJECT_ENABLED=1` in config/harness.env), the eject step reverts it on main and opens a pull request carrying the work back, byte for
byte, assigned to its author. That is a complete hand-back and it notifies a
PERSON. It notifies no session, and in this repository most commits are pushed
by a session that has since ended: the branch is `auto-eject/<sha12>`, the
commit that produced it carries a `Worktree:` trailer naming the effort, and
nobody working here tomorrow morning has any reason to look for either.

This is the message the session that made the commit would have wanted. It
cannot reach the session that pushed, which is gone; it reaches the next one to
open in this checkout, which is the session that would otherwise build on a
branch whose work is no longer on main.

WHAT IT SAYS AND WHAT IT WILL NOT DO. It names each open hand-back, its pull
request number, and the commit that came off. When one of them names THIS
worktree it says so first, because that is the one whose author is probably
reading. It never opens, closes, comments on or merges anything: a hand-back is
a person's decision and this is a notice.

FAIL OPEN, ALWAYS, and quietly. Every other hook here is load-bearing for
correctness; this one is a courtesy. No network, no token, a slow GitHub, a
checkout with no remote: all of them mean no notice, never a blocked session.
The whole thing is bounded by one `gh` call with a short timeout, and the
answer is cached for ten minutes so a burst of sessions costs one round trip.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parents[3] / ".claude" / "project.json"
CACHE_TTL_SECONDS = 600
GH_TIMEOUT_SECONDS = 8
#: `auto-eject/<sha12>`, the branch `_eject_build_branch` pushes. The sha is the
#: commit the gate rejected, which is the one fact a reader needs to find their
#: own work in the pull request.
BRANCH = re.compile(r"^auto-eject/([0-9a-f]{7,40})$")


def _repo_slug() -> str:
    """`owner/name` from .claude/project.json, the one place the repo is named.

    Raises when the template is still empty, which the caller turns into no
    notice: a repository nobody has run setup-github.py on has no hand-backs.
    """
    slug = json.loads(CONFIG_PATH.read_text())["repo"]
    if not slug:
        raise ValueError("project.json names no repo yet")
    return slug


def _project_dir() -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


def _cache_path() -> Path:
    return Path(
        os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
    ) / "harness-eject-notice.json"


def _worktree_slug() -> str:
    """The slug of the worktree this session is in, or "" in the shared checkout.

    Read off the path rather than off git, because the guards in this repository
    key on the worktree PATH and never on the branch name, and a notice that
    disagreed with the guards about which worktree this is would be worse than
    no notice.
    """
    parts = Path(os.getcwd()).resolve().parts
    if ".claude" in parts:
        index = parts.index(".claude")
        if len(parts) > index + 2 and parts[index + 1] == "worktrees":
            return parts[index + 2]
    return ""


def _open_handbacks() -> list[dict]:
    """Open `auto-eject/*` pull requests, from cache when it is fresh."""
    cache = _cache_path()
    try:
        held = json.loads(cache.read_text())
        if time.time() - float(held.get("at", 0)) < CACHE_TTL_SECONDS:
            return list(held.get("prs", []))
    except Exception:
        pass

    try:
        done = subprocess.run(
            ["gh", "pr", "list", "--repo", _repo_slug(), "--state", "open",
             "--limit", "20", "--json", "number,title,headRefName,url"],
            capture_output=True, text=True, timeout=GH_TIMEOUT_SECONDS,
        )
        if done.returncode != 0:
            return []
        rows = [row for row in json.loads(done.stdout) if BRANCH.match(row.get("headRefName", ""))]
    except Exception:
        return []

    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"at": time.time(), "prs": rows}))
    except Exception:
        pass
    return rows


def _trailer(sha: str, key: str) -> str:
    """One trailer value off a commit in the local checkout, or "".

    Offline on purpose: the rejected commit was on main, so this checkout has
    it, and reading it here costs nothing and needs no token.
    """
    try:
        done = subprocess.run(
            ["git", "-C", str(_project_dir()), "log", "-1", "--format=%B", sha],
            capture_output=True, text=True, timeout=5,
        )
        if done.returncode != 0:
            return ""
        for line in done.stdout.splitlines():
            if line.startswith(f"{key}:"):
                return line.split(":", 1)[1].strip()
    except Exception:
        return ""
    return ""


def _lines() -> list[str]:
    handbacks = _open_handbacks()
    if not handbacks:
        return []

    here = _worktree_slug()
    mine, others = [], []
    for row in handbacks:
        match = BRANCH.match(row.get("headRefName", ""))
        if not match:
            continue
        sha = match.group(1)
        effort = _trailer(sha, "Worktree")
        where = f", from worktree {effort}" if effort else ""
        text = f"  #{row['number']}: {sha[:12]} came off main{where}"
        if here and effort == here:
            mine.append(text + "  <- this worktree")
        else:
            others.append(text)

    if not mine and not others:
        return []

    out = [
        "A commit from this repository was rejected by the deploy gate and is "
        "waiting in a hand-back pull request. The work is on the branch, "
        "unchanged; fix the failure there and land it on main as one commit, "
        "because landing is what re-tests it. Do not re-push the same commit "
        "to main, and do not press merge on the pull request.",
    ]
    out.extend(mine + others)
    if mine:
        out.append(
            "The marked one is the worktree this session is in, so it is most "
            "likely the work being picked up here."
        )
    return out


def main() -> int:
    try:
        lines = _lines()
    except Exception:
        return 0
    if not lines:
        return 0
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": "\n".join(lines),
    }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
