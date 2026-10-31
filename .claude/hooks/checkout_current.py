#!/usr/bin/env python3
"""Session-start and stop hook: keep the shared checkout on `main` current, and
say so when it cannot.

It replaces a one-line shell blob (`git rebase -q --autostash origin/main
2>/dev/null || { git rebase --abort; exit 0; }`) that did the same work and
threw every failure away: silent on the fetch failing, on the rebase failing,
on the push failing. An unresolved merge in the shared checkout makes
`--autostash` fail on every session end, and with the blob nobody is told; the
first sign is some unrelated hook erroring because the checkout never received
it.

So the rule this hook exists to hold is not "catch the checkout up". It is
**never fail silently at this**. Catching up is best effort; reporting is not.

**It does not resolve anything.** A conflict needs a person, and a hook that
started resolving files on its own is a worse problem than the one it solves.
It reports the reason git gave, names the command to run, and gets out of the
way.

**It runs against `CLAUDE_PROJECT_DIR`, on purpose**, which is the shared
checkout even for a worktree session. This hook is *about* the shared checkout,
so a worktree session ending is exactly the moment worth using to check on it.

Once per session, because a session ending twice is not two problems.

**BOTH ENDS.** Catching up only at the end has a hole with two shapes. A session
that starts hours after the last one ended, or after somebody pushed from
another machine, spends its whole life on a checkout nobody has moved; and a
session that is killed rather than stopped never runs the Stop half at all.
Both are invisible, because a stale checkout does not fail, it just quietly
answers about old code.

At session start it does the catching up and the reporting and nothing else:
saving memory and pushing are things a session has earned by the end and has
not earned at the beginning. `CLAUDE_HOOK=SessionStart` in the hook's command
is what says which end it is. Memory is committed only where the repository
tracks `.claude/memory`; where it is git-ignored, git reports nothing to save.

**Run it before any session-start hook that compares something against the
shared checkout's HEAD** (a repository index, say): run first, that hook would
call a checkout that is ten commits behind `origin/main` "current".

FAILURE POLICY: never blocks, never raises, always exits 0. It writes to stderr,
which the harness shows as a note. `CHECKOUT_CURRENT=0` disarms it.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

#: How many commits behind is worth a word. One is a normal race with another
#: session pushing; a checkout that has stopped moving is the thing to catch.
BEHIND_ENOUGH_TO_SAY = 3

#: What git printed, trimmed to the part a person acts on. The whole of a failed
#: rebase is a screen of hints nobody reads at the end of a session.
REASON_LINES = 4


def git(args, cwd, capture=True):
    """Run git and return (ok, output). Never raises, whatever git does."""
    try:
        done = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=capture,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False, ""
    output = ((done.stdout or "") + (done.stderr or "")).strip()
    return done.returncode == 0, output


def on_main(checkout):
    """True when the checkout has `main` checked out; this hook owns nothing else."""
    ok, branch = git(["symbolic-ref", "--short", "HEAD"], checkout)
    return ok and branch == "main"


def save_memory(checkout):
    """Commit `.claude/memory` if a session wrote to it, the way the blob did."""
    ok, dirty = git(["status", "--porcelain", "--", ".claude/memory"], checkout)
    if not ok or not dirty:
        return
    git(["add", ".claude/memory"], checkout)
    git(["commit", "-q", "-m", "memory: auto-save", "--", ".claude/memory"], checkout)


def behind(checkout):
    """How many commits `origin/main` has that `main` does not, or None."""
    ok, count = git(["rev-list", "--count", "main..origin/main"], checkout)
    if not ok or not count.isdigit():
        return None
    return int(count)


#: The header git prints before listing the untracked files it will not clobber.
IN_THE_WAY = "untracked working tree files would be overwritten"


def in_the_way(said):
    """The untracked paths git named as blocking the update, if that is why.

    Parsed out of the message rather than recomputed, so this can only ever act
    on files git itself pointed at.
    """
    if IN_THE_WAY not in said:
        return []
    return [
        line.strip()
        for line in said.splitlines()
        if line.startswith(("\t", "    ")) and line.strip()
    ]


def already_what_is_coming(checkout, path):
    """True when `path` is untracked and byte-identical to origin/main's copy.

    Both halves are required. Untracked, so nothing anybody committed is
    touched; identical, so removing it loses nothing at all, because the update
    is about to write those exact bytes back.

    It exists because a file placed by hand blocks a fast-forward even when its
    content is right, which git refuses on principle rather than on content
    (identical content, still "would be overwritten"). A
    session that copies a missing hook into place to stop it erroring therefore
    wedges the very update that would have made the copy unnecessary.
    """
    ok, status = git(["status", "--porcelain", "--", path], checkout)
    if not ok or not status.startswith("??"):
        return False
    ok, theirs = git(["rev-parse", f"origin/main:{path}"], checkout)
    if not ok:
        return False
    ok, mine = git(["hash-object", "--", path], checkout)
    return ok and mine == theirs


def clear_the_way(checkout, said):
    """Remove only the blocking files that are already what is arriving.

    Returns True when every path git named qualified and was removed, so the
    caller may retry. One that does not qualify stops the whole thing: a
    partial clearing would leave a checkout half-prepared for an update that
    still cannot happen.
    """
    blocking = in_the_way(said)
    if not blocking:
        return False
    if not all(already_what_is_coming(checkout, path) for path in blocking):
        return False
    for path in blocking:
        try:
            (Path(checkout) / path).unlink()
        except OSError:
            return False
    return True


def catch_up(checkout):
    """Try to move `main` onto `origin/main`. Returns the reason it could not.

    Fast-forward first and rebase only if that is refused, which is the reverse
    of the blob's order and matters: a fast-forward cannot conflict, so the
    common case never touches the stash at all. An aborted rebase leaves the
    checkout exactly as it was found, which is the one thing this may not get
    wrong.
    """
    ok, said = git(["merge", "--ff-only", "origin/main"], checkout)
    if ok:
        return ""
    if clear_the_way(checkout, said):
        ok, said = git(["merge", "--ff-only", "origin/main"], checkout)
        if ok:
            return ""
    ok, said = git(["rebase", "--autostash", "origin/main"], checkout)
    if ok:
        return ""
    git(["rebase", "--abort"], checkout)
    return said


def unmerged(checkout):
    """The paths git says are in an unresolved merge, which block everything."""
    ok, listed = git(["diff", "--name-only", "--diff-filter=U"], checkout)
    return listed.splitlines() if ok and listed else []


def reason(said, blocked):
    """What to tell a person, in the order they can act on it."""
    if blocked:
        return (
            "an unresolved merge is in the way: "
            + ", ".join(blocked[:REASON_LINES])
            + ". Resolve those, `git add` them, then `git rebase --continue` or "
            "`git merge --abort`."
        )
    trimmed = "; ".join(said.splitlines()[:REASON_LINES]) if said else "git said nothing"
    return f"git refused: {trimmed}"


def marker_path(checkout, payload):
    """Where this session records that it has already said this once."""
    session_id = str(payload.get("session_id") or os.getpid())
    safe = "".join(char for char in session_id if char.isalnum() or char in "-_")
    return Path(checkout) / ".claude" / "state" / f"checkout-said-{safe}"


def claim_the_one_word(marker):
    """True the first time this session reaches here; False every time after."""
    if marker.exists():
        return False
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("said once\n")
    except OSError:
        return False
    return True


def main():
    if os.environ.get("CHECKOUT_CURRENT", "1") == "0":
        return
    try:
        payload = json.loads(sys.stdin.read())
    except Exception:
        payload = {}
    checkout = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    if not on_main(checkout):
        return
    # A session beginning has written nothing to save and has nothing to push;
    # it only needs the checkout under it to be the one everybody else is on.
    starting = os.environ.get("CLAUDE_HOOK") == "SessionStart"
    if not starting:
        save_memory(checkout)
    if not git(["fetch", "-q", "origin", "main"], checkout)[0]:
        return
    count = behind(checkout)
    if count is None:
        return
    if count:
        said = catch_up(checkout)
        if said and count >= BEHIND_ENOUGH_TO_SAY:
            if claim_the_one_word(marker_path(checkout, payload)):
                print(
                    f"The shared checkout at {checkout} is {count} commits behind "
                    f"origin/main and cannot catch itself up: {reason(said, unmerged(checkout))}\n"
                    "Until it does, it runs that many commits' worth of stale hooks "
                    "and skills, and a hook added on main will error there for every "
                    "session. Nothing else is affected; this is said once per session.",
                    file=sys.stderr,
                )
            return
    if starting:
        return
    # `git()` returns (ok, output), so the count is the SECOND element; the
    # first only says whether the command ran.
    ran, ahead = git(["rev-list", "--count", "origin/main..main"], checkout)
    if ran and ahead.strip() not in ("", "0"):
        git(["push", "-q", "origin", "main"], checkout)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
