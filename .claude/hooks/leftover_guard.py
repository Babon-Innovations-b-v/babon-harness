#!/usr/bin/env python3
"""Stop hook: a session may not end leaving its own work uncommitted.

Work a session leaves uncommitted is invisible to any pre-commit hook, because
nothing was committed at all: a fix sits in the tree while the build stays red,
or a rewrite is written, built, reported working and never committed, so what
ships is the old version and the user finds out by using the product.

This hook is only possible because of worktrees. In the shared checkout "dirty"
is everybody's and a report on it is noise; in a session worktree every dirty
path is the session's own. So it runs ONLY when the session's directory is a
linked worktree under ``.claude/worktrees/``, and stays quiet everywhere else.

It blocks at most ONCE per session. The marker is written BEFORE the block is
emitted, so a crash between the two leaves the guard silent rather than turning
session end into a loop.

FAILURE POLICY: fail-open. Anything unreadable or unexpected exits 0 with no
output, which ends the session normally. ``LEFTOVER_GUARD=0`` disarms it.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

MAX_LISTED = 20


def git_out(args, cwd):
    """Run git and return its stdout, or None on any failure."""
    try:
        done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    except OSError:
        return None
    return done.stdout if done.returncode == 0 else None


def session_worktree(cwd):
    """The worktree root when `cwd` is a session worktree, else None.

    A session worktree is a LINKED worktree (its git dir is not the shared
    common dir) whose root sits under ``<main checkout>/.claude/worktrees/``.
    """
    git_dir = git_out(["rev-parse", "--path-format=absolute", "--git-dir"], cwd)
    common = git_out(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd)
    toplevel = git_out(["rev-parse", "--show-toplevel"], cwd)
    if git_dir is None or common is None or toplevel is None:
        return None
    if git_dir.strip() == common.strip():
        return None
    worktrees_dir = Path(common.strip()).parent / ".claude" / "worktrees"
    root = Path(toplevel.strip())
    if worktrees_dir not in root.parents:
        return None
    return root


def dirty_paths(worktree_root):
    """The paths this session would leave behind, worktree-relative."""
    status = git_out(["status", "--porcelain"], worktree_root)
    if not status:
        return []
    return [line[3:] for line in status.splitlines() if len(line) > 3]


def marker_path(worktree_root, payload):
    """Where this session records that it has already been told once."""
    session_id = str(payload.get("session_id") or os.getpid())
    safe = "".join(char for char in session_id if char.isalnum() or char in "-_")
    return worktree_root / ".claude" / "state" / f"leftover-blocked-{safe}"


def claim_the_one_block(marker):
    """True the first time this session reaches here; False every time after.

    Writes the marker before the caller emits anything, so a failure to write
    means no block rather than a block that repeats.
    """
    if marker.exists():
        return False
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("blocked once\n")
    except OSError:
        return False
    return True


def reason(paths):
    """What the session is told, once."""
    listed = "\n".join(f"  {path}" for path in paths[:MAX_LISTED])
    if len(paths) > MAX_LISTED:
        listed += f"\n  ... and {len(paths) - MAX_LISTED} more"
    return (
        "This worktree still holds uncommitted work, and it is yours: nobody "
        "else writes here.\n" + listed + "\n"
        "Work that exists only in a working tree is invisible to the gate. Commit "
        "it, stash it deliberately, or say in the close comment why it stays. "
        "Then stop again; this is said once per session."
    )


def main():
    if os.environ.get("LEFTOVER_GUARD", "1") == "0":
        return
    payload = json.loads(sys.stdin.read())
    if payload.get("stop_hook_active"):
        return
    cwd = payload.get("cwd") or os.getcwd()
    worktree_root = session_worktree(cwd)
    if worktree_root is None:
        return
    paths = dirty_paths(worktree_root)
    if not paths:
        return
    if not claim_the_one_block(marker_path(worktree_root, payload)):
        return
    print(json.dumps({"decision": "block", "reason": reason(paths)}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Fail-open: a session that cannot end is worse than a torn commit.
        pass
    sys.exit(0)
