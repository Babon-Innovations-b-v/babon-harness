#!/usr/bin/env python3
"""Run this repository's own hooks: every entry in .claude/hooks/local/hooks.json whose event and matcher fit.

WHY. .claude/settings.json is one file shared by every repository on this harness, so a hook only one repository has
cannot be wired in it. Settings call this dispatcher on every event instead, and each repository lists its own hooks
in .claude/hooks/local/hooks.json: a JSON list of {"event", "matcher", "command", "timeout"}. An entry runs when its
event is this call's ``hook_event_name`` and its matcher (a regex, fullmatched like Claude Code's own; empty or "*"
matches all) fits the call's tool name, session source or agent type. Its command runs through the shell from the
repository root, with this call's payload on stdin, one entry after another in the file's order.

The repository is the one this file sits in, so a worktree's copy reads the worktree's manifest.

WHAT IT RETURNS, the way one hook would:
- any entry exits 2: exit 2 with every blocking entry's stderr joined, so the tool, prompt or stop is refused;
- else the first JSON answer that decides something (``permissionDecision``, ``decision``, ``updatedInput``,
  ``updatedToolOutput``, ``updatedMCPToolOutput``; a deny or block before an allow) is printed as it came, with
  every entry's ``additionalContext`` and ``systemMessage`` merged into it;
- plain stdout is context on SessionStart and UserPromptSubmit, where Claude Code reads it so, and stderr elsewhere.

FAILURE POLICY: fails open. A missing or broken manifest, an entry that crashes, an entry past its timeout and the
dispatcher's own crash all let the call through; only an entry's exit 2 or its JSON can refuse.
"""

import json
import os
import re
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / ".claude/hooks/local/hooks.json"
DEFAULT_TIMEOUT = 60
PLAIN_IS_CONTEXT = {"SessionStart", "UserPromptSubmit"}
DECIDING = ("permissionDecision", "updatedInput", "updatedToolOutput", "updatedMCPToolOutput")


def entries():
    """The manifest's entries, or none when it is missing or unreadable."""
    if not MANIFEST.is_file():
        return []
    try:
        found = json.loads(MANIFEST.read_text())
    except (OSError, ValueError) as error:
        print(f"dispatch: {MANIFEST} unreadable, local hooks skipped: {error}", file=sys.stderr)
        return []
    return [entry for entry in found if isinstance(entry, dict) and entry.get("command")]


def fits(entry, payload):
    """Whether an entry answers this call: its event, then its matcher against what the event is matched on."""
    if entry.get("event") != payload.get("hook_event_name"):
        return False
    matcher = entry.get("matcher") or ""
    subject = payload.get("tool_name") or payload.get("source") or payload.get("agent_type") or ""
    if matcher in ("", "*") or not subject:
        return True
    try:
        return re.fullmatch(matcher, subject) is not None
    except re.error:
        return False


def run(entry, raw):
    """(exit code, stdout, stderr) of one entry; None when it could not start or ran past its timeout."""
    try:
        child = subprocess.Popen(entry["command"], shell=True, cwd=ROOT, text=True, start_new_session=True,
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError:
        return None
    try:
        out, err = child.communicate(raw, timeout=entry.get("timeout") or DEFAULT_TIMEOUT)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGKILL)
        child.communicate()
        print(f"dispatch: {entry['command']} ran past its timeout, skipped", file=sys.stderr)
        return None
    return child.returncode, out.strip(), err.strip()


def decides(answer):
    """0 for a deny or block, 1 for any other decision, None for an answer that decides nothing."""
    specific = answer.get("hookSpecificOutput") or {}
    if specific.get("permissionDecision") == "deny" or answer.get("decision") == "block":
        return 0
    if "decision" in answer or any(key in specific for key in DECIDING):
        return 1
    return None


def merged(event, chosen, contexts, messages):
    """The one answer: the chosen decision as it came, with every context and message added."""
    answer = dict(chosen or {})
    if contexts:
        specific = dict(answer.get("hookSpecificOutput") or {})
        specific["hookEventName"] = event
        specific["additionalContext"] = "\n\n".join(contexts)
        answer["hookSpecificOutput"] = specific
    if messages:
        answer["systemMessage"] = "\n".join(messages)
    return answer


def main():
    raw = sys.stdin.read()
    payload = json.loads(raw)
    event = payload.get("hook_event_name", "")
    blocks, contexts, messages, notes = [], [], [], []
    chosen, rank = None, None
    for entry in entries():
        if not fits(entry, payload):
            continue
        result = run(entry, raw)
        if result is None:
            continue
        code, out, err = result
        if code == 2:
            blocks.append(err or f"blocked by {entry['command']}")
            continue
        if err:
            notes.append(err)
        if code != 0 or not out:
            continue
        try:
            answer = json.loads(out)
        except ValueError:
            answer = None
        if not isinstance(answer, dict):
            (contexts if event in PLAIN_IS_CONTEXT else notes).append(out)
            continue
        context = (answer.get("hookSpecificOutput") or {}).get("additionalContext")
        if context:
            contexts.append(context)
        if answer.get("systemMessage"):
            messages.append(answer["systemMessage"])
        level = decides(answer)
        if level is not None and (rank is None or level < rank):
            chosen, rank = answer, level
    if blocks:
        print("\n".join(blocks), file=sys.stderr)
        return 2
    if notes:
        print("\n".join(notes), file=sys.stderr)
    answer = merged(event, chosen, contexts, messages)
    if answer:
        print(json.dumps(answer))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # noqa: BLE001 - the dispatcher fails open, whatever broke
        print(f"dispatch: failed open: {error!r}", file=sys.stderr)
        sys.exit(0)
