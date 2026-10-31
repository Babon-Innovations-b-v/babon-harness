"""Nextcloud Talk transport, make a video-call link the assistant can put on an
agenda (slice 1).

A meeting can be a video call. Nextcloud Talk (the `spreed` app, already
live on cloud.example.org as the alert chat channel) has a room API: create a
public room and its token IS the call link (`<base>/call/<token>`), which
opens straight into a browser video call, no account needed for a guest.

The room is public AND its attendees are invited into it (`invite_users`).
Those are not the same thing and the difference is the point: public
is what lets an outsider join with the link alone, being a participant is
what lets a teammate open that link as themselves. A room nobody was invited
to offers everyone the guest screen, teammates included, and getting off it
costs a full login with a second factor.

This is the one place the agenda tools reach the Talk room API, same role
as `caldav.py` for CalDAV: it carries the assistant account login (the same
`AGENDA_APP_PASSWORD` app-password the calendar writes use, verified able
to create rooms) and speaks OCS. Stdlib only, the openclaw
image installs no Nextcloud client.

The LINK is what travels: it goes in the event's LOCATION on each
attendee's calendar (so it shows and is clickable), and the 15-min-before
reminder reads it back out of LOCATION. So this module also owns the two
tiny helpers that recognise and pull a Talk call link out of free text
(`is_call_link` / `extract_call_link`), so "what counts as a call link"
lives in exactly one place.

FAILURE POLICY: Tier-2 best-effort. `create_call_room` returns the link
on success or None on any failure (missing token, non-2xx, network), with
a log line; it never raises, so a Talk outage degrades a video booking to
a plain one instead of breaking the chat turn.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

from apps.assistant.core.tools.agenda import caldav

log = logging.getLogger("openclaw.agenda.talk")

_TOKEN_ENV = "AGENDA_APP_PASSWORD"
_TIMEOUT_SECONDS = 15
# Nextcloud Talk room types (spreed OCS API): 3 = public, joinable by
# anyone with the link, a guest opens it in the browser with no account,
# which is what a shared call link needs.
_ROOM_TYPE_PUBLIC = "3"
_CALL_PATH = "/call/"
_BOT_ID_ENV = "OPENCLAW_TALK_BOT_ID"
# Talk offers the invitable accounts per ROOM, not globally: an account with
# no admin rights (assistant has none) may only ask who it could add to a room it
# already owns, which is why every lookup here needs a room token.
_AUTOCOMPLETE_PATH = (
    "/ocs/v2.php/core/autocomplete/get?format=json&search=&itemType=call"
    "&itemId={room}&shareTypes[]=0&limit=50"
)
_PARTICIPANTS_PATH = "/ocs/v2.php/apps/spreed/api/v4/room/{room}/participants"


def _base_url() -> str:
    return caldav.BASE_URL.rstrip("/")


def create_call_room(name: str) -> str | None:
    """Create a public Talk room named `name` and return its call link
    (`<base>/call/<token>`), or None on any failure.

    Authenticates as the assistant account with the same app-password the
    calendar writes use. The link is shared by both attendees of a meeting,
    so it must be created ONCE and the same link written to each calendar:
    the caller (the `create_video_call` tool) is responsible for that.
    """
    token = os.environ.get(_TOKEN_ENV, "").strip()
    if not token:
        log.warning("%s not set; cannot create a Talk room", _TOKEN_ENV)
        return None
    status, body = _ocs_post(
        "/ocs/v2.php/apps/spreed/api/v4/room?format=json",
        {"roomType": _ROOM_TYPE_PUBLIC, "roomName": name[:200] or "Videogesprek"},
        token,
    )
    if status is None or status >= 300:
        log.warning("Talk room create failed: HTTP %s", status)
        return None
    try:
        room_token = json.loads(body)["ocs"]["data"]["token"]
    except (ValueError, KeyError, TypeError) as exc:
        log.warning("Talk room create returned no token: %s", exc)
        return None
    if not room_token:
        return None
    # Enable the Notulen bot on this room so its call_started/call_ended events
    # reach the auto-record webhook. Best-effort: a booked call still works
    # without it (it just would not auto-record until the bot is on the room).
    enable_bot(room_token)
    return f"{_base_url()}{_CALL_PATH}{room_token}"


def enable_bot(room_token: str) -> None:
    """Enable the Notulen Talk bot on `room_token` so it receives that room's
    call events. Skipped silently when `OPENCLAW_TALK_BOT_ID` is unset (before
    the bot is installed); a failure only logs. The bot drives auto-recording
   ."""
    bot_id = os.environ.get(_BOT_ID_ENV, "").strip()
    token = os.environ.get(_TOKEN_ENV, "").strip()
    if not bot_id or not token:
        return
    status, _ = _ocs_post(f"/ocs/v2.php/apps/spreed/api/v1/bot/{room_token}/{bot_id}", {}, token)
    if status is None or status >= 300:
        log.warning("enabling Talk bot on room %s returned HTTP %s", room_token, status)


def token_from_link(call_link: str) -> str | None:
    """The room token inside `call_link`, or None when it is not a call link.

    The LINK is what travels (it lives in an event LOCATION), so a caller
    holding only the link needs this to reach the room API about it again.
    """
    if not call_link or _CALL_PATH not in call_link:
        return None
    tail = call_link.rsplit(_CALL_PATH, 1)[1]
    return tail.split("?")[0].split("#")[0].strip().strip("/") or None


def invitable_users(room_token: str) -> dict[str, str]:
    """Who this room could invite: `{display name: Nextcloud user id}`.

    Returns {} on any failure (Tier-2): a booking must never fail because the
    invite list could not be read.
    """
    token = os.environ.get(_TOKEN_ENV, "").strip()
    if not token:
        return {}
    status, body = _ocs_get(_AUTOCOMPLETE_PATH.format(room=room_token), token)
    if status is None or status >= 300:
        log.warning("Talk autocomplete on room %s returned HTTP %s", room_token, status)
        return {}
    try:
        rows = json.loads(body)["ocs"]["data"]
    except (ValueError, KeyError, TypeError) as exc:
        log.warning("Talk autocomplete returned no usable list: %s", exc)
        return {}
    users: dict[str, str] = {}
    for row in rows or []:
        user_id = str(row.get("id", "")).strip()
        label = str(row.get("label", "")).strip()
        if user_id and str(row.get("source", "users")) == "users":
            users[label or user_id] = user_id
    return users


def match_user(name: str, users: dict[str, str]) -> str | None:
    """The Nextcloud user id for the teammate called `name`, or None when no
    account matches it or more than one does.

    Two ways to match, both EXACT and never a substring: the account's display
    name, or the first dot-separated part of the user id's local part
    (`sam@example.org` -> `sam`). Exactness is the point. Putting the
    wrong person in a meeting room is worse than putting nobody in it, so an
    ambiguous name resolves to None and that person joins by link like anyone
    else.
    """
    wanted = name.strip().lower()
    if not wanted:
        return None
    matched = {
        user_id
        for label, user_id in users.items()
        if label.strip().lower() == wanted
        or user_id.split("@")[0].split(".")[0].strip().lower() == wanted
    }
    return matched.pop() if len(matched) == 1 else None


def add_participant(room_token: str, user_id: str) -> bool:
    """Add one Nextcloud user to `room_token` as a real participant. True iff
    Talk accepted it; a failure only logs (Tier-2)."""
    token = os.environ.get(_TOKEN_ENV, "").strip()
    if not token:
        return False
    status, _ = _ocs_post(
        _PARTICIPANTS_PATH.format(room=room_token) + "?format=json",
        {"newParticipant": user_id, "source": "users"},
        token,
    )
    if status is None or status >= 300:
        log.warning("inviting %s to room %s returned HTTP %s", user_id, room_token, status)
        return False
    return True


def invite_users(call_link: str, names: list[str]) -> list[str]:
    """Put the teammates in `names` into the room behind `call_link` as real
    participants, and return the names that actually got in.

    WHY a public room still invites people. The room stays public so an
    outside guest can join with the link alone, but a teammate who is a
    participant opens that same link as themselves instead of landing on
    Talk's guest screen. The guest screen costs a full login, and
    Nextcloud asks for a second factor on every login, so the
    invite is the difference between clicking a link and doing the whole
    dance fifteen minutes before a meeting. It also gives the minutes real
    names to map the speaker labels onto (`_room_attendees` in the notulen
    ingest reads exactly this participant list).

    Tier-2 throughout: an unreachable Talk, a name matching no account and a
    refused invite each cost that one person their seat by name, never the
    call link.
    """
    room = token_from_link(call_link)
    if room is None or not names:
        return []
    users = invitable_users(room)
    if not users:
        return []
    invited: list[str] = []
    for name in names:
        user_id = match_user(name, users)
        if user_id is None:
            log.info("no single Nextcloud account matches %r; not inviting", name)
            continue
        if add_participant(room, user_id):
            invited.append(name)
    return invited


def _ocs_get(path: str, token: str) -> tuple[int | None, str]:
    """One authenticated OCS GET as the assistant account; (status, text), or
    (None, '') on a network error."""
    credentials = base64.b64encode(f"{caldav.agenda_user()}:{token}".encode()).decode()
    request = urllib.request.Request(
        _base_url() + path,
        method="GET",
        headers={
            "OCS-APIRequest": "true",
            "Accept": "application/json",
            "Authorization": f"Basic {credentials}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        log.warning("Talk OCS get network error: %s", error)
        return None, ""


def _ocs_post(path: str, form: dict[str, str], token: str) -> tuple[int | None, str]:
    """One authenticated OCS POST as the assistant account; (status, text), or
    (None, '') on a network error. `OCS-APIRequest` is required by every
    Nextcloud OCS endpoint."""
    credentials = base64.b64encode(f"{caldav.agenda_user()}:{token}".encode()).decode()
    request = urllib.request.Request(
        _base_url() + path,
        data=urllib.parse.urlencode(form).encode(),
        method="POST",
        headers={
            "OCS-APIRequest": "true",
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {credentials}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        log.warning("Talk OCS post network error: %s", error)
        return None, ""


def is_call_link(text: str) -> bool:
    """Whether `text` (an event LOCATION) carries a Nextcloud Talk call
    link, the mark the reminder scan looks for to know a meeting is a
    video call."""
    return extract_call_link(text) is not None


def extract_call_link(text: str) -> str | None:
    """The Talk call link inside `text`, or None. A LOCATION may hold just
    the link or the link plus other words, so pull the first whitespace-
    delimited token that looks like our `<base>/call/<token>` URL."""
    if not text or _CALL_PATH not in text:
        return None
    for token in text.replace(",", " ").split():
        if _CALL_PATH in token and token.lower().startswith(("http://", "https://")):
            return token.rstrip(".,;)")
    return None
