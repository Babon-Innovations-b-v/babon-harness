#!/usr/bin/env python3
"""PreToolUse guard: a session may not route around the torn-commit guard.

Reads the Claude Code PreToolUse hook payload on stdin (``{tool_name,
tool_input, cwd, ...}``) and blocks two things, both on TOKENS via shlex, so a
quoted commit message can never trip them (the same fix issue_guard.py
carries for `git push -f`):

1. THE BYPASS. ``git commit --no-verify`` / ``-n``, or a command whose
   environment prefix sets ``TORN_GUARD=0`` or ``LEFTOVER_GUARD=0``.
   Those overrides exist for a human at a terminal who can see what they are
   waiving. A session waiving them gets the torn commit the guard exists to
   stop, with an extra step.

2. THE SHARED CHECKOUT, gated by ``WORKTREE_GUARD`` (default "1", armed). A
   ``git commit`` in the MAIN checkout is blocked while another session's
   worktree under ``.claude/worktrees/`` holds a live lock, and the message
   says how to move. It judges the repository the COMMAND targets, not the one
   the session sits in (``target_cwd``), so a commit in another repository on
   this machine is that repository's business. It is armed by default because
   the worktree habit does not arrive on its own: several sessions sharing one
   checkout tear commits, publish each other's work and rebase under each other.

   Note what it does NOT do, so nobody reads more safety into it than is there:
   it fires only while some OTHER session is live in a worktree. If everybody is
   in the shared checkout it never fires at all. It makes the shared checkout
   uncomfortable once anyone has moved out; it cannot make anyone move.
   ``WORKTREE_GUARD=0`` disarms it.

FAILURE POLICY: fail-open. Any parse error, unknown shape, or unrelated call
exits 0 (allow). Exit 2 + stderr is the only block path (the harness feeds
stderr back to the model as the block reason).
"""

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

BYPASS_FLAGS = ("--no-verify", "-n")
BYPASS_ENV = ("TORN_GUARD=0", "LEFTOVER_GUARD=0")

LOCK_PID_RE = re.compile(r"pid (\d+)")

_BYPASS_HELP = (
    "BLOCKED: {what} routes around the torn-commit guard.\n"
    "The guard blocks a commit whose staged files need something the commit "
    "leaves behind, which is exactly the check a session cannot do by eye.\n"
    "If the guard is wrong here, fix what it names (git add the path, or "
    "git stash push it) and commit again.\n"
    "The override is a human's: a person can run it at a terminal. A session "
    "may not."
)


def block(message):
    print(message, file=sys.stderr)
    sys.exit(2)


def git_out(args, cwd):
    """Run git and return its stripped stdout, or "" on any failure."""
    try:
        done = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True
        )
    except OSError:
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


GIT_OPTIONS_WITH_A_VALUE = ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path")


def git_subcommand(tokens, start):
    """The subcommand of the `git` word at `start`, past git's own options; "" when there is none."""
    index = start + 1
    while index < len(tokens) and tokens[index].startswith("-"):
        index += 2 if tokens[index] in GIT_OPTIONS_WITH_A_VALUE else 1
    return tokens[index].rstrip(";&|") if index < len(tokens) else ""


def is_git_commit(tokens):
    """True when some `git` word in the command runs `commit` as its subcommand.

    Only the subcommand counts: `git log --grep commit`, or a comment body that names git and later says commit, is
    not a commit.
    """
    starts = [index for index, word in enumerate(tokens) if word == "git" or word.endswith("/git")]
    return any(git_subcommand(tokens, start) == "commit" for start in starts)


def bypass_in(tokens):
    """The bypass this command carries, or None."""
    if is_git_commit(tokens) and any(flag in tokens for flag in BYPASS_FLAGS):
        return "git commit --no-verify"
    for assignment in BYPASS_ENV:
        if assignment in tokens:
            return assignment
    return None


def _resolve_dir(raw, base):
    """`raw` as a directory, relative to `base`, or `base` when it is not one."""
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = base / candidate
    try:
        return candidate if candidate.is_dir() else base
    except OSError:
        return base


def target_cwd(tokens, cwd):
    """The directory the command's git actually runs in.

    The payload's ``cwd`` is the SESSION's, and a command can leave it: it may
    open with ``cd <path> &&``, or pass ``-C <path>``. Judging one repository's
    commit against another's checkout is a false block with no route around it,
    because a session inside a worktree cannot run git aimed outside it either.

    Only those two forms are read, and only a LEADING ``cd``. Anything subtler
    (a shell variable, a second ``cd`` mid-chain, a subshell) falls back to the
    session's cwd, which is the old behaviour and the safe direction: this guard
    exists to make the shared checkout uncomfortable, so guessing wrong should
    leave it firing rather than silent.
    """
    base = Path(cwd)
    for index, token in enumerate(tokens):
        if token != "git":
            continue
        rest = tokens[index + 1:]
        if len(rest) > 1 and rest[0] == "-C":
            return _resolve_dir(rest[1], base)
    if len(tokens) > 1 and tokens[0] == "cd":
        # shlex keeps a `;` on the word before it: `cd <path>; git commit`
        return _resolve_dir(tokens[1].rstrip(";"), base)
    return base


def in_main_checkout(cwd):
    """True when `cwd` sits in the main checkout rather than a linked worktree."""
    git_dir = git_out(["rev-parse", "--path-format=absolute", "--git-dir"], cwd)
    common = git_out(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd)
    return bool(git_dir) and git_dir == common


def pid_alive(pid):
    """True if a process with this pid currently exists."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def live_session_worktrees(cwd):
    """The session worktrees currently locked by a live process.

    Reads the same ``locked`` files .claude/scripts/worktree-reap.py reads, so
    the two agree on what "live" means. Anything unreadable counts as not live:
    this guard fails open.
    """
    common = git_out(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd)
    if not common:
        return []
    worktrees_dir = Path(common) / "worktrees"
    if not worktrees_dir.is_dir():
        return []
    live = []
    for entry in sorted(worktrees_dir.iterdir()):
        lock_file = entry / "locked"
        if not lock_file.is_file():
            continue
        try:
            match = LOCK_PID_RE.search(lock_file.read_text())
        except OSError:
            continue
        if match and pid_alive(int(match.group(1))):
            live.append(entry.name)
    return live


def check_bypass(tokens):
    """Block a session's attempt to waive a guard that is a human's to waive."""
    bypass = bypass_in(tokens)
    if bypass:
        block(_BYPASS_HELP.format(what=bypass))


def check_shared_checkout(tokens, cwd):
    """Block a commit in the shared checkout while another session's worktree is live."""
    if os.environ.get("WORKTREE_GUARD", "1") != "1":
        return
    if not is_git_commit(tokens):
        return
    where = target_cwd(tokens, cwd)
    if not in_main_checkout(where):
        return
    live = live_session_worktrees(where)
    if not live:
        return
    block(
        "BLOCKED: committing in the shared checkout while another session is live "
        "in: " + ", ".join(live) + ".\n"
        "Several sessions in one checkout tear each other's commits. Move "
        "your work into your own worktree first:\n"
        "  git stash push -- <your paths>\n"
        "  EnterWorktree({name: \"<slug>\"}) then bash .claude/scripts/worktree-setup.sh\n"
        "  git stash pop\n"
        "(CLAUDE.md: a session that writes files works in its own worktree.)"
    )


def main():
    payload = json.loads(sys.stdin.read())
    if payload.get("tool_name") != "Bash":
        return
    command = (payload.get("tool_input") or {}).get("command", "")
    if "git" not in command and "_GUARD=" not in command:
        return
    tokens = shlex.split(command)  # may raise on odd quoting -> caller fails open
    check_bypass(tokens)
    check_shared_checkout(tokens, payload.get("cwd") or os.getcwd())


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        # Fail-open: never wedge a tool call because the guard tripped over an
        # input shape it did not expect.
        sys.exit(0)
