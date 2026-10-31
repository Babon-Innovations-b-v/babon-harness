#!/usr/bin/env python3
"""Reap orphaned git worktrees left behind by crashed Claude sessions.

Each Claude worktree under .claude/worktrees/ is locked while its session is live, and the lock
reason carries the session pid. A crash leaves the lock behind, and every later session skips the
worktree as "in use by another live session" forever.

A worktree is reaped only when its lock pid is dead AND it is clean (no uncommitted changes, HEAD
already on origin/main). Dirty orphans are reported, never deleted, so no work is lost. An unlocked
worktree (a finished agent's, or one made by hand) is reaped only when it is clean and merged AND
untouched for IDLE_HOURS, because finished agents leave many of them behind: they fill the disk, and
they sit inside the repository tree, where a check that walks the tree finds files from other
branches. A dirty or unmerged unlocked one is never touched.

Run standalone (`python3 .claude/scripts/worktree-reap.py`) or via the SessionStart hook. Exit
status is always 0 so it never blocks a session.
"""
import json
import os
import re
import subprocess
import time
from pathlib import Path

LOCK_PID_RE = re.compile(r"pid (\d+)")
IDLE_HOURS = 6


def git_out(args, cwd=None):
    """Run git, returning (returncode, stripped stdout)."""
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return proc.returncode, proc.stdout.strip()


def git_common_dir():
    """The shared .git directory, asked of git because in a linked worktree `.git` is a file."""
    code, common = git_out(["rev-parse", "--path-format=absolute", "--git-common-dir"],
                           cwd=Path(__file__).resolve().parent)
    return Path(common) if code == 0 else None


def pid_alive(pid):
    """True if a process with this pid currently exists."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # it exists; we just can't signal it
        pass
    return True


def lock_pid(common_dir, worktree_name):
    """The pid recorded in this worktree's lock file, or None if unlocked."""
    lock_file = common_dir / "worktrees" / worktree_name / "locked"
    if not lock_file.is_file():
        return None
    match = LOCK_PID_RE.search(lock_file.read_text())
    return int(match.group(1)) if match else None


def idle_hours(common_dir, worktree_name):
    """Hours since this worktree's HEAD or index last changed, from git's own admin files (not its reflog, which
    repository-wide housekeeping rewrites)."""
    admin = common_dir / "worktrees" / worktree_name
    stamps = [path.stat().st_mtime for path in (admin / "HEAD", admin / "index") if path.exists()]
    return (time.time() - max(stamps)) / 3600 if stamps else 0.0


def is_clean(worktree_path):
    """True when no uncommitted changes (untracked files included) and HEAD is on origin/main.

    `main` is the deploy interface here, so once a worktree's commits are on origin/main its branch
    is disposable. The local origin/main is used, no fetch: if it is stale, the worst case is that a
    merged worktree is kept, never that unmerged work is deleted. A missing ref keeps the worktree.
    """
    code, dirty = git_out(["status", "--porcelain"], cwd=worktree_path)
    if code != 0 or dirty:
        return False
    code, _ = git_out(["merge-base", "--is-ancestor", "HEAD", "origin/main"], cwd=worktree_path)
    return code == 0


def remove_worktree(entry, worktrees_dir):
    """Remove one orphan worktree and its auto-named branch; False when git refuses."""
    _, branch = git_out(["symbolic-ref", "--short", "HEAD"], cwd=entry)
    git_out(["worktree", "unlock", str(entry)], cwd=worktrees_dir)
    code, _ = git_out(["worktree", "remove", "--force", str(entry)], cwd=worktrees_dir)
    if code != 0:
        return False
    # Only the EnterWorktree "worktree-*" naming, so a meaningfully named branch is never touched.
    if branch.startswith("worktree-"):
        git_out(["branch", "-D", branch], cwd=worktrees_dir)
    return True


def reap():
    """Names of the worktrees reaped, and of the stale-locked ones kept because of their work."""
    common_dir = git_common_dir()
    if common_dir is None:
        return [], []
    worktrees_dir = common_dir.parent / ".claude" / "worktrees"
    if not worktrees_dir.is_dir():
        return [], []
    self_root = Path(__file__).resolve().parents[2]
    reaped, kept_dirty = [], []
    for entry in sorted(worktrees_dir.iterdir()):
        if not entry.is_dir() or entry == self_root:
            continue
        pid = lock_pid(common_dir, entry.name)
        if pid is None:
            if idle_hours(common_dir, entry.name) >= IDLE_HOURS and is_clean(entry) \
                    and remove_worktree(entry, worktrees_dir):
                reaped.append(entry.name)
            continue
        if pid_alive(pid):
            continue
        if is_clean(entry) and remove_worktree(entry, worktrees_dir):
            reaped.append(entry.name)
        else:
            kept_dirty.append(entry.name)
    if reaped:
        git_out(["worktree", "prune"], cwd=worktrees_dir)
    return reaped, kept_dirty


def report(reaped, kept_dirty):
    """One line for the session; empty when there is nothing worth saying."""
    lines = []
    if reaped:
        lines.append(f"Reaped {len(reaped)} orphaned worktree(s): {', '.join(reaped)}.")
    if kept_dirty:
        lines.append(
            f"Left {len(kept_dirty)} stale-locked worktree(s) with uncommitted work: "
            f"{', '.join(kept_dirty)}. Recover or discard by hand."
        )
    return " ".join(lines)


def main():
    context = report(*reap())
    if context and os.environ.get("CLAUDE_HOOK") == "SessionStart":
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                                 "additionalContext": context}}))
    elif context:
        print(context)


if __name__ == "__main__":
    main()
