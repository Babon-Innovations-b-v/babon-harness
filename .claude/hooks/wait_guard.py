#!/usr/bin/env python3
"""PreToolUse guard on Bash: no waiting in the foreground.

An agent's turn that comes more than 5 minutes after its previous one re-writes its whole context to the prompt cache,
and most of those long gaps are foreground sleeps, poll loops and long foreground runs. Claude Code blocks a command
that *starts* with ``sleep`` in some sessions but not in others (in background sessions ``sleep 300; tail log`` runs),
so this guard blocks, for a Bash call not run with ``run_in_background``:

- a ``sleep`` over ``LONGEST_SLEEP`` seconds anywhere in the command;
- a poll loop: ``while`` or ``until`` with a ``sleep`` in it, or a ``for`` loop sleeping over ``LONGEST_LOOP_SLEEP``
  seconds a round;
- a ``tail`` that follows a file (``-f``, ``-F``, ``--follow``, ``tail --pid=<pid> -f /dev/null``), on its own or
  piped into a ``grep -m1``: it ends only when it is killed, so it is a wait however it is wrapped;
- a ``timeout`` over ``LONGEST_SLEEP`` seconds around a wait (a ``sleep``, ``wait``, ``inotifywait``, ``watch``,
  ``gh run watch``, ``kubectl wait``, or a ``bash -c`` script that sleeps or waits);
- a command the project names as long-running in ``.claude/project.json``, under ``wait_guard.foreground_runs``: each
  entry is ``{"run": <regex>, "unless": <regex or null>, "what": <how the block names it>}``, matched per command
  segment, and the entry's ``unless`` exempts a segment (a dry run, say). ``wait_guard.way_out`` adds the project's
  own route out (a detach flag, a wrapper) to the block message.

The block message names the way out.

FAILURE POLICY: fail-open. Any parse error or unknown shape exits 0 (allow). Exit 2 + stderr is the only block path.
"""

import json
import pathlib
import re
import sys

LONGEST_SLEEP = 60
LONGEST_LOOP_SLEEP = 5
_CONFIG_PATH = pathlib.Path(__file__).resolve().parents[2] / ".claude" / "project.json"
_UNITS = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}
# A shell sleep (not time.sleep): a word boundary, then a number with an optional unit.
_SLEEP = re.compile(r"(?<![\w.])sleep\s+(\d+(?:\.\d+)?)([smhd]?)\b")
_MESSAGE = re.compile(r"""(?<![\w-])-m\s+(["'])[\s\S]*?(?<!\\)\1""")  # a commit message is words, not a wait
_UNBOUNDED_LOOP = re.compile(r"(?<![\w.-])(while|until)\s[\s\S]*?(?<![\w.-])do\b([\s\S]*?)(?<![\w.-])done\b")
_FOR_LOOP = re.compile(r"(?<![\w.-])for\s[\s\S]*?(?<![\w.-])do\b([\s\S]*?)(?<![\w.-])done\b")
# The words a segment may start with before the command it runs: a `(`, NAME=value, nohup, stdbuf, a timeout.
_LEAD = r"^\s*[({]?\s*(?:[A-Za-z_]\w*=\S*\s+|nohup\s+|stdbuf\s+(?:-\S+\s+)+|timeout\s+(?:-\S+\s+)*\S+\s+)*"
_TAIL_FOLLOW = re.compile(_LEAD + r"tail\s(?:.*\s)?(?:-[A-Za-z]*[fF][A-Za-z]*|--follow(?:=\S*)?)(?=\s|$)")
_TIMEOUT = re.compile(r"(?:^|[;&|\n(])\s*timeout\s+(?:-\S+\s+)*(\d+(?:\.\d+)?)([smhd]?)\s+([\s\S]*)")
_WAITS = re.compile(r"^(?:sleep|wait|inotifywait|watch|gh\s+run\s+watch|kubectl\s+(?:\S+\s+)*?wait)\b")
_SHELL_SCRIPT = re.compile(r"^(?:\S*/)?(?:ba|z|da)?sh\s+(?:-\S+\s+)*-c\b")
_WAIT_IN_SCRIPT = re.compile(r"(?<![\w.-])(?:sleep|wait|inotifywait)\b")
_SEGMENT = re.compile(r"&&|\|\||[;|\n]")
_WAY_OUT = (
    "Never wait in the foreground (CLAUDE.md): start the command with run_in_background: true and go on with other "
    "work or end your turn; the completion notice wakes you. To wait for a condition, put the until-loop in that "
    "background command: one notice when it ends. Some Claude Code versions hand a Monitor script to this hook "
    "as plain Bash, so its sleep loops and tail -f can be blocked too; Monitor always suits kubectl logs -f or a "
    "WebSocket."
)


def _settings():
    """The ``wait_guard`` block of .claude/project.json, or {} when there is none."""
    try:
        return json.loads(_CONFIG_PATH.read_text()).get("wait_guard") or {}
    except (OSError, ValueError, AttributeError):
        return {}


def _foreground_runs(settings):
    """(runs, unless, what) per long-running command the project lists; an entry that does not compile is skipped."""
    runs = []
    for entry in settings.get("foreground_runs") or []:
        try:
            unless = re.compile(entry["unless"]) if entry.get("unless") else None
            runs.append((re.compile(entry["run"]), unless, str(entry.get("what") or "a long run")))
        except (KeyError, TypeError, re.error):
            continue
    return runs


def sleeps(text):
    """The length in seconds of each shell sleep in the text."""
    return [float(match.group(1)) * _UNITS[match.group(2)] for match in _SLEEP.finditer(text)]


def long_sleep(command):
    """A sleep over LONGEST_SLEEP anywhere in the command, or None."""
    longest = max(sleeps(command), default=0)
    return f"a sleep of {longest:g} s" if longest > LONGEST_SLEEP else None


def poll_loop(command):
    """A while/until loop that sleeps, or a for loop sleeping more than LONGEST_LOOP_SLEEP a round, or None."""
    for match in _UNBOUNDED_LOOP.finditer(command):
        if sleeps(match.group(2)):
            return f"a {match.group(1)} loop that sleeps"
    for match in _FOR_LOOP.finditer(command):
        if any(seconds > LONGEST_LOOP_SLEEP for seconds in sleeps(match.group(1))):
            return "a for loop that sleeps between rounds"
    return None


def tail_follow(command):
    """A command segment that runs a tail following a file, or None."""
    if any(_TAIL_FOLLOW.search(segment) for segment in _SEGMENT.split(command)):
        return "a tail that follows a file"
    return None


def long_timeout(command):
    """A timeout over LONGEST_SLEEP seconds around a wait, or None."""
    for match in _TIMEOUT.finditer(command):
        seconds = float(match.group(1)) * _UNITS[match.group(2)]
        wrapped = match.group(3)
        waits = _WAITS.match(wrapped) or (_SHELL_SCRIPT.match(wrapped) and _WAIT_IN_SCRIPT.search(wrapped))
        if seconds > LONGEST_SLEEP and waits:
            return f"a timeout of {seconds:g} s around a wait"
    return None


def long_run(command, runs):
    """A command segment that runs one of the project's long-running commands in the foreground, or None."""
    for segment in _SEGMENT.split(command):
        for pattern, unless, what in runs:
            if pattern.search(segment) and not (unless and unless.search(segment)):
                return f"{what} in the foreground"
    return None


def blocked(tool_input, settings):
    """Why this Bash call waits in the foreground, or None."""
    if tool_input.get("run_in_background"):
        return None
    if "timeout_ms" in tool_input:
        # A Monitor script that arrives carrying its timeout is the background
        # watch this guard sends people to. Not every Claude Code sends it: on
        # 2026-11-08 a Monitor call arrived with only `command` and
        # `description`, and the transcript records the call only after its
        # hooks run, so there such a loop is blocked; the way-out message says so.
        return None
    command = _MESSAGE.sub("-m ''", tool_input.get("command") or "")
    return (long_sleep(command) or poll_loop(command) or tail_follow(command) or long_timeout(command)
            or long_run(command, _foreground_runs(settings)))


def main():
    try:
        payload = json.load(sys.stdin)
        settings = _settings()
        reason = blocked(payload.get("tool_input") or {}, settings) if payload.get("tool_name") == "Bash" else None
    except Exception:  # fail-open: a broken guard must never wedge a tool call
        sys.exit(0)
    if reason:
        extra = str(settings.get("way_out") or "")
        print(f"Blocked: {reason}. {_WAY_OUT}" + (f" {extra}" if extra else ""), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
