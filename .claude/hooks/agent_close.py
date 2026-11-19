#!/usr/bin/env python3
"""Hook: a sub-agent closes when its work is done, never sits open waiting on its own background work.

Two things left agents open in the task list for hours. A sub-agent started a long command with ``run_in_background``
(a copy, a render, a test run) and ended its turn "waiting" on it: a sub-agent with background work of its own stays
open until that work ends. And a sub-agent's final report arrived, but the session that started it never stopped it
(TaskStop), so it stayed listed, idle and resumable. This hook works at the moments those start and never blocks:

- ``SubagentStart``: every sub-agent gets the hand-back rule (``HAND_BACK``) as context, whatever its brief says.
- ``PreToolUse`` on a sub-agent's ``run_in_background`` Bash call: the same rule once more, beside that call.
- ``SubagentStop`` of a background sub-agent: the agent is written down as finished, or as holding its own background
  work when a background command or Monitor it started has not ended.
- ``PostToolUse`` and ``UserPromptSubmit`` in the session that started it: the session is told to close each agent
  written down (TaskStop), at most ``REMINDERS`` times an agent.
- ``PreToolUse`` on TaskStop, or the agent starting again (``SubagentStart``): the agent is crossed off.

The project may add its own way to start a run detached (``agent_close.detached`` in .claude/project.json).

FAILURE POLICY: fail-open. Anything unreadable exits 0 with no output. Nothing here ever blocks: exit 0 always.
"""

import json
import os
import pathlib
import re
import sys
import tempfile

REMINDERS = 2
_CONFIG_PATH = pathlib.Path(__file__).resolve().parents[2] / ".claude" / "project.json"
_LAUNCHED = re.compile(r"running in background with ID: (\w+)|Monitor started[^\n]*?\b(?:task|ID)[: ]+(\w+)")
_ENDED = re.compile(r"<task-id>(\w+)</task-id>[\s\S]*?<status>(?:completed|failed|killed|stopped|expired)</status>")
HAND_BACK = (
    "You are a sub-agent: you close only when you return, and the session that started you reads only your final "
    "report. Never end your turn to wait on your own background work (a run_in_background command or a Monitor): a "
    "sub-agent that does stays open, idle, until that work ends, often hours. Run what ends within a few minutes in "
    "the foreground. Start anything longer detached, so it outlives you: setsid nohup <command> > <log> 2>&1 "
    "< /dev/null &, its last line saying done or failed. Then return your final report with its pid, its log, the "
    "command that checks it and the line that means it ended; the session that started you watches it with Monitor "
    "and starts the next step. Before your final report, stop every background command and Monitor you started "
    "(TaskStop)."
)


def _project():
    """The ``agent_close`` block of .claude/project.json, or {} when there is none."""
    try:
        return json.loads(_CONFIG_PATH.read_text()).get("agent_close") or {}
    except (OSError, ValueError, AttributeError):
        return {}


def hand_back():
    """The hand-back rule, with the project's own detached runner when it names one."""
    detached = str(_project().get("detached") or "")
    return HAND_BACK + (f" In this project start it detached with: {detached}" if detached else "")


def ledger(payload):
    """The folder of the agents written down for the session that started them (one JSON file an agent)."""
    root = pathlib.Path(os.environ.get("AGENT_CLOSE_DIR") or pathlib.Path(tempfile.gettempdir()) / "agent-close")
    agent_transcript = payload.get("agent_transcript_path")
    # A sub-agent's transcript sits in <session>/subagents/, so its parent's id is that folder's name.
    session = pathlib.Path(agent_transcript).parents[1].name if agent_transcript else payload.get("session_id")
    return root / re.sub(r"[^\w-]", "_", str(session or "none"))


def held_work(agent_transcript):
    """The ids of the background commands and Monitors the sub-agent started and that have not ended."""
    try:
        text = pathlib.Path(agent_transcript).read_text()
    except (OSError, TypeError):
        return []
    text = text.replace("\\n", "\n")
    launched = [first or second for first, second in _LAUNCHED.findall(text)]
    ended = set(_ENDED.findall(text))
    stopped = set(re.findall(r'"name":\s*"(?:TaskStop|KillShell)",\s*"input":\s*\{[^}]*"(?:task_id|shell_id)":\s*"(\w+)"',
                             text))
    return sorted({job for job in launched if job not in ended | stopped})


def ran_in_background(agent_transcript):
    """Whether the sub-agent was launched in the background (its meta file says so); True when unknown."""
    try:
        meta = pathlib.Path(agent_transcript).with_suffix(".meta.json")
        return json.loads(meta.read_text()).get("requestShape", "background") == "background"
    except (OSError, TypeError, ValueError, AttributeError):
        return True


def write_down(payload):
    """SubagentStop: record a background sub-agent as finished or as holding its own background work."""
    agent, transcript = payload.get("agent_id"), payload.get("agent_transcript_path")
    folder = ledger(payload)
    if not agent or not ran_in_background(transcript) or (folder / f"{agent}.closed").exists():
        return
    folder.mkdir(parents=True, exist_ok=True)
    record = {"agent": agent, "type": payload.get("agent_type") or "", "held": held_work(transcript), "said": 0}
    (folder / f"{agent}.json").write_text(json.dumps(record))


def cross_off(folder, agent, closed):
    """The agent leaves the ledger; ``closed`` marks it stopped, so a late SubagentStop does not write it down again."""
    (folder / f"{agent}.json").unlink(missing_ok=True)
    if closed:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{agent}.closed").write_text("")
    else:
        (folder / f"{agent}.closed").unlink(missing_ok=True)


def reminder(folder):
    """The line telling the session to close the agents written down; each is said at most REMINDERS times."""
    lines = []
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        record = json.loads(path.read_text())
        record["said"] += 1
        if record["said"] < REMINDERS:
            path.write_text(json.dumps(record))
        else:
            path.unlink()
        agent = record["agent"]
        if record["held"]:
            lines.append(f"Sub-agent {agent} ended its turn holding its own background work "
                         f"({', '.join(record['held'])}), so it stays open until that ends. Ask it once with "
                         "SendMessage to hand back (start the work detached, return its pid, log and check command, "
                         f"stop its background tasks), or TaskStop {agent} when nothing it runs must survive.")
        else:
            lines.append(f"Sub-agent {agent} has returned its final report and is still open: close it now with "
                         f"TaskStop (task_id {agent}).")
    return " ".join(lines)


def answer(payload):
    """The context this event adds (an empty string adds none), after updating the ledger."""
    event, in_agent = payload.get("hook_event_name"), bool(payload.get("agent_id"))
    tool, tool_input = payload.get("tool_name"), payload.get("tool_input") or {}
    if event == "SubagentStart":
        cross_off(ledger(payload), payload.get("agent_id"), closed=False)
        return hand_back()
    if event == "SubagentStop":
        write_down(payload)
        return ""
    if event == "PreToolUse" and tool == "TaskStop":
        stopped = tool_input.get("task_id") or tool_input.get("shell_id")
        if stopped:
            cross_off(ledger(payload), str(stopped), closed=True)
        return ""
    if event == "PreToolUse" and in_agent and tool == "Bash" and tool_input.get("run_in_background"):
        return hand_back()
    if event in ("PostToolUse", "UserPromptSubmit") and not in_agent:
        return reminder(ledger(payload))
    return ""


def main():
    try:
        payload = json.load(sys.stdin)
        said = answer(payload) if isinstance(payload, dict) else ""
    except Exception:  # fail-open: a broken hook must never wedge a tool call or a sub-agent
        sys.exit(0)
    if said:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": payload["hook_event_name"],
                                                 "additionalContext": said}}))
    sys.exit(0)


if __name__ == "__main__":
    main()
