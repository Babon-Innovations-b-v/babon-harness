"""`my_actions` read tool, the assistant checks its OWN action log.

A model can deny a send its action log records: a passive action-log block
in the prompt does not stop it reasoning from memory instead of reading it,
and a confident false
"I didn't" breaks trust worse than the original slip. This tool turns that log
into something the model can actively QUERY before it says whether it did or
did not do something: the teammate messages it sent, issues it opened / closed
/ assigned, calendar events it added or removed, newest first, optionally
filtered by a word (a name, "issue", "agenda").

It also lists every Signal message the assistant sent anyone from OUTSIDE the
conversation it is in. The gateway answers every inbound message in
one chat session, while the weekday brief and the advisor run in isolated
cron sessions and the container's own pages, pen, patrol and meeting reminders go
straight to signal-cli, so that session never saw the question a "Yes"
answers, and a reply could be taken as an answer to a days-old message about
something else. Every send path appends what it delivered to
`chat_turns` as an `assistant` row, which is what this reads; a
`message_teammate` send is in both tables and is shown once.

And it lists what the assistant is holding and has not sent yet: pings in the notify pen
and pages in `page_hold`, which quiet hours and the morning gate keep back
Without them "not sent yet" reads as "never arrived": a batch-done
held in the pen overnight would look to the chat like a completion that
never came.

Each held line carries its local time, and pages held since the last brief
that were dropped as no longer news are listed too, because the weekday brief
reads this to report the night: a page it names is not sent a second time
(`core/page_hold.py`), and an outage that ended overnight is a line in the
morning report rather than nothing at all.

And it lists every card the assistant filed that is now closed but still mutes its
subject, with what it silenced since the last brief (`core/closed_card_mutes`,
one cached GitHub call): such a mute is kept on purpose, and shown here
instead of lifted.

Read-only: it reads `state.assistant_actions`, `chat_turns`, `notify_pen` and
`page_hold` and writes nothing, so it sits in the shared investigation surface
next to the other reads (no new concern).

Tool-module grammar: `NAME`, `DEFINITION`, `execute`.

FAILURE POLICY: Tier-2, a read fault returns as text to the LLM, never raises
into the loop.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from apps.assistant.core import people, quiet_hours, state
from apps.assistant.core.state import chat_turns
from apps.assistant.core.tools.meta.text import truncate
from apps.assistant.core.tools.meta.whats_changed import report_window_start

NAME = "my_actions"

_MAX_SCAN = 40
_MAX_SHOWN = 20
#: How much of a sent message is shown: enough to tell which question a reply
#: answers, which an 80-character summary was not.
_SENT_SHOWN_CHARS = 300

DEFINITION: dict[str, Any] = {
    "name": NAME,
    "description": (
        "Your own recent actions from your action log: every message you sent "
        "(briefs and pages too), issue and calendar changes, and what you are "
        "holding and have not sent yet (quiet hours hold pages overnight until "
        "the morning). Check here before saying whether you did something or "
        "whether something reached you."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "about": {
                "type": "string",
                "description": "Filter: a name, 'issue' or 'agenda'.",
            },
        },
    },
}


def _matches(action: dict[str, Any], needle: str) -> bool:
    """True if `needle` appears anywhere in an action's readable fields."""
    haystack = " ".join(
        str(action.get(field, ""))
        for field in ("kind", "target", "summary", "detail", "actor")
    ).lower()
    return needle in haystack


def _sent_entries(team_messages: set[str]) -> list[dict[str, Any]]:
    """Messages the assistant delivered, shaped like action rows, minus the ones
    `team_messages` already holds (a `message_teammate` send writes both)."""
    entries = []
    for turn in chat_turns.recent_sent_turns(_MAX_SCAN):
        text = str(turn.get("text", ""))
        if text[:500] in team_messages:
            continue
        person = people.identify_by_number(str(turn.get("sender", "")))
        entries.append({
            "kind": "signal_sent",
            "target": person.name if person else str(turn.get("sender", "")),
            "summary": text[:_SENT_SHOWN_CHARS],
            "detail": text,
            "actor": "assistant",
            "created_at": turn.get("created_at", ""),
        })
    return entries


def _waiting(about: str) -> list[str]:
    """Pings in the pen and pages in the hold queue, oldest first, one line
    each, filtered by `about`. Tier-2: a failed read is the one line saying so."""
    try:
        pings = state.unflushed_pings()
        held = list(reversed(state.recent_held(_MAX_SHOWN)))
    except Exception as exc:  # noqa: BLE001, Tier-2: hand the fault to the LLM
        return [f"could not read what is waiting to be sent: {type(exc).__name__}: {exc}"]
    lines = [
        f"[{_local_clock(ping.get('received_at'))}] held in the pen -> {ping.get('subject', '')}"
        for ping in pings
        if not about or about in f"{ping.get('subject', '')} {ping.get('body', '')}".lower()
    ]
    lines += [
        f"[{_local_clock(page.get('held_at'))}] held to send -> "
        f"{page.get('subject') or ''}: {str(page.get('text', ''))[:120]}"
        for page in held
        if not about or about in f"{page.get('subject', '')} {page.get('text', '')}".lower()
    ]
    return lines[:_MAX_SHOWN]


def _since_the_last_brief() -> datetime:
    """Where the morning brief's window opens, the window both night sections use."""
    return report_window_start("morning", datetime.now(timezone.utc))


def _closed_cards(about: str) -> list[str]:
    """Closed cards whose mute still stands, one line each. Tier-2: a failed
    read, GitHub's included, is the one line saying so, never an empty list."""
    from apps.assistant.core import closed_card_mutes  # lazy: it imports the gh package this registry is still loading

    try:
        lines = closed_card_mutes.report(_since_the_last_brief())
    except Exception as exc:  # noqa: BLE001, Tier-2: hand the fault to the LLM
        return [f"could not read which filed cards are closed: {type(exc).__name__}: {exc}"]
    return [line for line in lines if not about or about in line.lower()][:_MAX_SHOWN]


def _dropped(about: str) -> list[str]:
    """Pages held since the last brief and dropped unsent, one line each, with
    why. Tier-2: a failed read is the one line saying so."""
    try:
        since = _since_the_last_brief().isoformat()
        pages = state.dropped_pages_since(since)
    except Exception as exc:  # noqa: BLE001, Tier-2: hand the fault to the LLM
        return [f"could not read the pages dropped overnight: {type(exc).__name__}: {exc}"]
    return [
        f"[{_local_clock(page.get('held_at'))}] held, then not sent -> "
        f"{page.get('subject') or ''}: {page.get('dropped_because') or ''}"
        for page in pages
        if not about or about in f"{page.get('subject', '')} {page.get('text', '')}".lower()
    ][:_MAX_SHOWN]


def _local_clock(moment: Any) -> str:
    """A stored UTC timestamp as the reader's own clock: weekday, minute and
    zone named, the way the brief reports a held page's arrival."""
    try:
        parsed = datetime.fromisoformat(str(moment))
    except ValueError:
        return f"{_stamp(moment)}Z"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return quiet_hours.local_moment(parsed).strftime("%a %H:%M local")


def _stamp(moment: Any) -> str:
    """The minute of a stored timestamp, as every line here shows it."""
    return str(moment or "")[:16].replace("T", " ")


def _render(action: dict[str, Any]) -> str:
    """One line of the answer: when, what, to whom, and the words."""
    stamp = _stamp(action.get("created_at"))
    if action["kind"] == "signal_sent":
        return f"[{stamp}Z] sent -> {action['target']}: {action['summary']}"
    if action["kind"] == "team_message":
        summary = str(action.get("detail") or action.get("summary", ""))[:_SENT_SHOWN_CHARS]
    else:
        summary = str(action.get("summary", ""))[:120]
    return (
        f"[{stamp}Z] {action['kind']} -> {action['target']}: {summary} "
        f"(asked by {action['actor']})"
    )


def execute(tool_input: dict[str, Any]) -> str:
    about = str(tool_input.get("about", "")).strip().lower()
    try:
        actions = state.recent_actions(_MAX_SCAN)
        team_messages = {
            str(action.get("detail", ""))[:500]
            for action in actions
            if action.get("kind") == "team_message"
        }
        actions = actions + _sent_entries(team_messages)
    except Exception as exc:  # noqa: BLE001, Tier-2: hand the fault to the LLM
        return f"could not read your action log: {type(exc).__name__}: {exc}"
    actions.sort(key=lambda action: str(action.get("created_at", "")), reverse=True)

    if about:
        actions = [action for action in actions if _matches(action, about)]
    waiting = _waiting(about)
    dropped = _dropped(about)
    closed = _closed_cards(about)
    if not actions and not waiting and not dropped and not closed:
        return (
            f"no actions in your log matching {about!r}" if about
            else "your action log is empty, you have not done anything logged yet"
        )
    parts = []
    if waiting:
        parts.append(
            "Waiting, not sent yet (quiet hours and the morning gate hold these "
            "until they open; a page the morning brief names by its subject is "
            "not sent again):\n" + "\n".join(waiting)
        )
    if dropped:
        parts.append(
            "Held since the last brief and dropped unsent (no longer news):\n"
            + "\n".join(dropped)
        )
    if closed:
        parts.append(
            "Muted by a card that is closed (the mute stays; the owner wants to see these):\n"
            + "\n".join(closed)
        )
    if actions:
        parts.append("\n".join(_render(action) for action in actions[:_MAX_SHOWN]))
    return truncate("\n\n".join(parts))
