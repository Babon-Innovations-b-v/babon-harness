"""`create_video_call` tool, the assistant makes a Nextcloud Talk video-call link
(slice 1).

When a meeting is a video call, the assistant first makes ONE call link with this
tool, then adds the meeting to each attendee's calendar with `agenda_act`,
putting that same link in the event's `location`. One link, shared by
everyone: it must be made once here, not once per calendar, or the
attendees would each get a different room and never meet.

Naming the attendees here also puts them IN the room, which is what makes
the link open as them rather than on Talk's guest screen. The room
stays public, so anyone else with the link still joins as a guest.

Same safety shape as the other outward writes (`agenda_act`/`github_act`),
scaled to a tiny blast radius (a throwaway public room):

  1. KILL SWITCH. Refuses unless ``ASSISTANT_VIDEO_CALL=1`` in the container env.
  2. OWN IDENTITY. Creates the room as the `assistant` Nextcloud account (the
     same app-password the calendar writes use).
  3. AUDIT. The created link lands in ``state.assistant_actions`` (kind
     ``video_call``) before it is reported, so every room the assistant opened is
     on the record.

Tool-module grammar: NAME, DEFINITION, execute.

FAILURE POLICY: refusal + a failed create return as text; the audit write
is Tier-1 (propagates to the registry's defended catch, never a silent
skip).
"""
from __future__ import annotations

import html
from typing import Any

from apps.assistant.core.tools import write_guard
from apps.assistant.core.tools.agenda import talk

NAME = "create_video_call"

_ENABLE_ENV = "ASSISTANT_VIDEO_CALL"


DEFINITION: dict[str, Any] = {
    "name": NAME,
    "description": (
        "Make one Nextcloud Talk link for a video meeting. Make it once per "
        "meeting and put it in the `location` of every attendee's agenda_act "
        "event."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": "Room name, e.g. 'Alex & Sam'.",
            },
            "attendees": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Teammates in the call, e.g. ['Alex', 'Sam']; outside "
                    "guests are not listed."
                ),
            },
        },
    },
}


def execute(tool_input: dict[str, Any], actor: str = "assistant") -> str:
    disabled = write_guard.require_enabled(_ENABLE_ENV, "make a video call link")
    if disabled:
        return disabled
    # Decoded because the model sometimes writes "&amp;" for "&".
    topic = html.unescape(str(tool_input.get("topic", ""))).strip()
    attendees = [str(name).strip() for name in tool_input.get("attendees") or []]
    link = talk.create_call_room(topic or "Videogesprek")
    if link is None:
        return "making the video call link failed (Nextcloud Talk); it is not created."
    # Best-effort, and before the audit so the record says who was actually let
    # in rather than who was asked for.
    invited = talk.invite_users(link, [name for name in attendees if name])
    write_guard.audit(
        "video_call",
        link,
        topic or "Videogesprek",
        actor=actor,
        detail="invited: " + (", ".join(invited) if invited else "nobody"),
    )
    return (
        f"video call ready: {link}, put this link in the location when you add "
        "the meeting to each person's calendar (reuse the same link for everyone). "
        + (
            f"In the room already, so the link opens as themselves: {', '.join(invited)}."
            if invited
            else "Nobody could be put in the room, so everyone joins as a guest."
        )
    )
