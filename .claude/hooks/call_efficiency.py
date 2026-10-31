#!/usr/bin/env python3
"""Count tool-call waste per session, and say the bundle rule while it happens.

WHY THIS EXISTS. Issuing a tool call costs seconds of model reasoning, while
most commands return in under one, so a session that runs one fast read per
call spends its wall clock thinking rather than working. The rules that fix it
are written down (bundle independent shell work into one call; a repo question
is often one index call) and sessions drift off them mid-flow. A rule nobody
watches is a rule that holds for the first hour of a session and not the third.

WHAT IT DOES, and the half it deliberately does not. Two events, one file,
the `CLAUDE_HOOK` pattern `checkout_current.py` uses:

- **PostToolUse (Bash)**: keeps a per-session tally, and when `_STREAK`
  single, known-fast commands arrive in a row it injects one line naming
  them, at most `_NUDGES` times a session. The judgement is SHAPE, not
  timing: the payload carries no duration, and the shape is the point
  anyway, three separate calls each carrying one fast read is the pattern
  the bundle rule names, whatever each one cost.
- **Stop**: writes the session's row to `.claude/state/call-efficiency.jsonl`
  (one row per session, rewritten as the session grows) and says one line to
  the terminal, once per session, so drift shows up in numbers instead of a
  one-off hand measurement.

What it does NOT do is tell a session what an index knows about the thing it
is grepping for. This hook only counts and nudges.

THE CLASSIFIER IS ROUGH AND THAT IS PRICED. A separator inside quotes reads
as a bundle, a slow `grep` over a big tree reads as fast, and both cost one
wrong count in a tally, never a blocked call and never a false claim printed
as fact; the tally line says it counts shapes. Rough and always-on beats
precise and unbuilt here, the same trade `torn_commit_guard` documents.

FAILURE POLICY: fail-open and silent. A broken
payload, an unwritable state dir, its own crash: each exits 0 with no output.
``CALL_EFFICIENCY=0`` disarms it.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

#: How many single fast commands in a row earn the nudge. Two in a row is
#: often legitimate sequencing (read, then act on what it said); three reads
#: is the pattern the bundle rule was written against.
_STREAK = 3

#: Most nudges one session is given. Past that the session has heard it, and
#: a hook that nags every call is a hook that gets disarmed.
_NUDGES = 3

#: First words whose single command is near-always a sub-second read. Shape
#: list, not a benchmark: a command here can be slow on a big tree and the
#: cost is one wrong count.
_CHEAP = {
    "ls", "cat", "head", "tail", "grep", "rg", "wc", "stat", "pwd", "which",
    "file", "du", "df", "find", "echo", "printf", "tr", "cut", "sort",
    "uniq", "basename", "dirname", "realpath", "readlink", "env", "date",
}

#: Git subcommands that are reads. `git push` or `git commit` in its own call
#: is sequencing, not waste, so it resets the streak instead of feeding it.
_CHEAP_GIT = {
    "status", "log", "diff", "show", "rev-parse", "branch", "remote",
    "ls-files", "ls-tree", "describe", "reflog", "blame", "shortlog",
    "config", "worktree", "stash",
}

#: What separates two commands in one call. A call carrying any of these did
#: bundle its work, which is exactly what the rule asks for.
_SEPARATORS = ("&&", "||", ";", "|", "\n")

_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def repo_root() -> Path:
    """The checkout this hook belongs to, from its own location."""
    return Path(__file__).resolve().parents[2]


def state_path(root: Path, payload: dict) -> Path:
    """Where this session's tally lives, keyed by session."""
    session_id = str(payload.get("session_id") or os.getpid())
    safe = "".join(char for char in session_id if char.isalnum() or char in "-_")
    return root / ".claude" / "state" / f"calls-{safe}"


def tally_at(marker: Path) -> dict:
    """The tally so far, or a fresh one."""
    try:
        held = json.loads(marker.read_text())
    except (OSError, ValueError):
        held = {}
    return {
        "session": held.get("session", ""),
        "bash": held.get("bash", 0),
        "single_fast": held.get("single_fast", 0),
        "bundled": held.get("bundled", 0),
        "streak": held.get("streak", 0),
        "longest_streak": held.get("longest_streak", 0),
        "nudges": held.get("nudges", 0),
        "recent": held.get("recent", []),
        "said": held.get("said", False),
    }


def keep(marker: Path, tally: dict) -> None:
    """Write the tally back; a failure to write means no nudge, never a crash."""
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(tally))


def command_head(command: str) -> str:
    """The program a single command runs, past env assignments and paths."""
    words = command.strip().split()
    while words and _ASSIGNMENT.match(words[0]):
        words.pop(0)
    if not words:
        return ""
    head = words[0].rsplit("/", 1)[-1]
    if head == "git" and len(words) > 1:
        return f"git {words[1]}"
    return head


def is_bundled(command: str) -> bool:
    """Whether this call carries more than one command."""
    return any(mark in command for mark in _SEPARATORS)


def is_single_fast(command: str) -> bool:
    """Whether this call is one known-fast read on its own."""
    if is_bundled(command):
        return False
    head = command_head(command)
    if head.startswith("git "):
        return head.split()[1] in _CHEAP_GIT
    return head in _CHEAP


def nudge(recent: list[str]) -> str:
    """The one line said when the pattern shows, naming what it saw."""
    named = ", ".join(recent[-_STREAK:])
    return (
        f"{_STREAK} single fast commands in a row ({named}). Root CLAUDE.md: "
        "bundle independent shell work into one call that prints a labelled "
        "report; a repo question is often one call to the repository index."
    )


def on_bash(payload: dict, root: Path) -> None:
    """PostToolUse: count this call, and speak only on the exact pattern."""
    command = str((payload.get("tool_input") or {}).get("command") or "")
    if not command:
        return
    marker = state_path(root, payload)
    tally = tally_at(marker)
    tally["session"] = str(payload.get("session_id") or "")
    tally["bash"] += 1
    if is_bundled(command):
        tally["bundled"] += 1
        tally["streak"] = 0
    elif is_single_fast(command):
        tally["single_fast"] += 1
        tally["streak"] += 1
        tally["recent"] = (tally["recent"] + [command_head(command)])[-_STREAK:]
        tally["longest_streak"] = max(tally["longest_streak"], tally["streak"])
    else:
        tally["streak"] = 0
    speak = tally["streak"] == _STREAK and tally["nudges"] < _NUDGES
    if speak:
        tally["nudges"] += 1
    # Written BEFORE anything is emitted:
    # a failure to write means no nudge rather than a nudge every call.
    keep(marker, tally)
    if speak:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": nudge(tally["recent"]),
            }
        }))


def on_stop(payload: dict, root: Path) -> None:
    """Stop: land the session's row, and say the numbers once."""
    marker = state_path(root, payload)
    tally = tally_at(marker)
    if not tally["bash"]:
        return
    _land_row(root, tally)
    if not tally["said"]:
        tally["said"] = True
        keep(marker, tally)
        print(
            f"call-efficiency: {tally['bash']} Bash calls so far, "
            f"{tally['single_fast']} single fast, {tally['bundled']} bundled, "
            f"longest unbundled streak {tally['longest_streak']}, "
            f"{tally['nudges']} nudges. Shape counts, not timings; rows in "
            ".claude/state/call-efficiency.jsonl",
            file=sys.stderr,
        )


def _land_row(root: Path, tally: dict) -> None:
    """One row per session in the box-wide file, rewritten as the session grows."""
    rows_at = root / ".claude" / "state" / "call-efficiency.jsonl"
    mine = tally.get("session", "")
    kept = []
    try:
        for line in rows_at.read_text().splitlines():
            try:
                if json.loads(line).get("session") != mine:
                    kept.append(line)
            except ValueError:
                continue
    except OSError:
        pass
    kept.append(json.dumps({
        "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "session": mine,
        "bash": tally["bash"],
        "single_fast": tally["single_fast"],
        "bundled": tally["bundled"],
        "longest_streak": tally["longest_streak"],
        "nudges": tally["nudges"],
    }))
    rows_at.parent.mkdir(parents=True, exist_ok=True)
    rows_at.write_text("\n".join(kept) + "\n")


def main() -> None:
    if os.environ.get("CALL_EFFICIENCY", "1") == "0":
        return
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001 - fail-open, per the policy above
        return
    root = repo_root()
    event = os.environ.get("CLAUDE_HOOK", "")
    if event == "Stop":
        on_stop(payload, root)
    elif payload.get("tool_name") == "Bash":
        on_bash(payload, root)


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001, S110 - a tally may never break a session
        pass
