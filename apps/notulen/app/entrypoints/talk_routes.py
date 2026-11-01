"""Talk bot webhook: record every video call and turn it into minutes.

A Nextcloud Talk webhook bot (installed by `infra/media/connect-talk.sh`,
enabled on each room the assistant's `create_video_call` makes) POSTs the
call system messages here:

- `call_started` starts the recording as the room owner (the assistant's
  account, a moderator; the OCS recording API needs a moderator) and warms
  a GPU when the GPU tier is on.
- `call_ended` / `call_ended_everyone` hands the finished recording to
  `ingest_recording` (fetch, S3, minutes job) and releases the GPU.

So a call records itself and becomes minutes with nobody pressing record.

This route is HMAC-gated, not behind the single sign-on: each webhook carries
`X-Nextcloud-Talk-Signature` = HMAC-SHA256(`X-Nextcloud-Talk-Random` + raw
body, `TALK_BOT_SECRET`). The Caddyfile lets this one path past the login.

FAILURE POLICY: Tier-2 at the edge. A bad or absent signature is 401.
Anything after that (recording start, ingest) is best-effort and never 500s
the webhook: Talk retries webhooks, and a missing recording on a short call
is a normal skip. Start and ingest run on background threads so the webhook
returns at once; a lost meeting pages through `alert_recording.py`.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Header, HTTPException, Request

from apps.notulen.app.core.minutes.release_gpu import release_gpu
from apps.notulen.app.core.minutes.warm_gpu import warm_gpu
from apps.notulen.app.core.sessions.alert_recording import (
    alert_no_recording,
    alert_recording_not_started,
)
from apps.notulen.app.core.sessions.ingest_recording import ingest_recording
from apps.notulen.app.core.sessions.recording_guard import (
    ingest_with_wait,
    should_alert_no_recording,
    start_recording_with_retry,
)
from apps.notulen.app.shared.talk_account import basic_auth, nc_base

log = logging.getLogger("notulen")
router = APIRouter()

_CALL_STARTED = "call_started"
_CALL_ENDED = ("call_ended", "call_ended_everyone")
_TIMEOUT = 15

# Tokens of calls we have seen `call_started` for but not yet `call_ended`,
# mapped to their start wall-clock time. It is the "is this call still
# active?" signal the recording-start retry checks, and the source of the
# call duration the no-recording page uses. Best-effort in-process: a
# dashboard restart mid-call drops the entry, and the no-recording check
# then treats the duration as unknown (pages rather than lose it silently).
_ACTIVE_CALLS: dict[str, float] = {}


def _meeting_zone() -> ZoneInfo:
    """The zone a meeting's date is read in: the owner's, else UTC."""
    return ZoneInfo(os.environ.get("ASSISTANT_TIMEZONE", "").strip() or "UTC")


def _signature_ok(random_header: str | None, signature_header: str | None, raw_body: bytes) -> bool:
    """The Talk bot signature: HMAC-SHA256(random + raw body, shared secret),
    hex, compared constant-time. Missing secret or headers -> reject."""
    secret = os.environ.get("TALK_BOT_SECRET", "").strip()
    if not (secret and random_header and signature_header):
        return False
    digest = hmac.new(
        secret.encode(), (random_header.encode() + raw_body), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(digest, signature_header.strip().lower())


_TOKEN_RE = re.compile(r"^[a-z0-9]{6,}$")


def _room_token(payload: dict) -> str:
    """The conversation token from the Activity-Streams envelope. Talk puts the
    room on `target`; its `id` is the token (documented). Be robust to the real
    shape: also try `token`, the `object`-level id/token, and a value that is a
    full `.../call/<token>` URL or a path, taking the token segment. Validated
    against the Talk token grammar (lowercase alphanumeric) so a name/URL never
    slips through as a 'token'."""
    for holder in (payload.get("target") or {}, payload.get("object") or {}):
        if not isinstance(holder, dict):
            continue
        for key in ("id", "token"):
            value = str(holder.get(key) or "").strip()
            if not value:
                continue
            if "/call/" in value:
                value = value.rsplit("/call/", 1)[-1].split("?")[0].split("/")[0]
            elif "/" in value:
                value = value.rstrip("/").rsplit("/", 1)[-1]
            if _TOKEN_RE.match(value):
                return value
    return ""


@router.post("/api/talk/webhook")
async def _talk_webhook(
    request: Request,
    x_nextcloud_talk_signature: str | None = Header(default=None),
    x_nextcloud_talk_random: str | None = Header(default=None),
) -> dict:
    raw = await request.body()
    if not _signature_ok(x_nextcloud_talk_random, x_nextcloud_talk_signature, raw):
        raise HTTPException(status_code=401, detail="bad or missing Talk bot signature")
    try:
        payload = json.loads(raw.decode("utf-8", "replace"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="bad payload") from exc

    name = str((payload.get("object") or {}).get("name", ""))
    token = _room_token(payload)
    if not token:
        # Log loudly (WARNING) with the envelope so a future shape mismatch is
        # diagnosable from one real event, not another test call.
        log.warning("talk webhook: no room token; name=%r target=%r object=%r",
                    name, payload.get("target"), payload.get("object"))
        return {"ok": True, "ignored": "no room token"}

    if name == _CALL_STARTED:
        _ACTIVE_CALLS[token] = time.time()
        # Retry the start off the request path: it must keep asking until the
        # call is recordable, and never block or 500 the webhook.
        threading.Thread(target=_run_start_recording, args=(token,), daemon=True).start()
        # Ask for the GPU while the call runs, not after it.
        warm_gpu(token)
        return {"ok": True, "recording_started": token}
    if name in _CALL_ENDED:
        # Pop the active-call entry first so the still-running start-retry
        # thread sees the call ended and stops quietly; then ingest.
        started_at = _ACTIVE_CALLS.pop(token, None)
        duration_sec = time.time() - started_at if started_at is not None else None
        # Ingest off the request path: never block or 500 the webhook.
        threading.Thread(
            target=_ingest_call, args=(token, duration_sec), daemon=True
        ).start()
        return {"ok": True, "ingesting": token}
    return {"ok": True, "ignored": name}


def _post_start_recording(token: str) -> tuple[int, str]:
    """POST `status:1` to the OCS recording API as the room owner. Returns
    (HTTP status, body); `400 {"error":"call"}` means the call is not
    recordable yet (the retryable race)."""
    return _ocs_post(
        f"/ocs/v2.php/apps/spreed/api/v1/recording/{token}?format=json", {"status": "1"}
    )


def _run_start_recording(token: str) -> None:
    """Start the recording, retrying past the "call not in progress yet" race
    until it starts, the call ends, or the deadline passes; page on a real
    failure (never on the retryable race). On a real start, post the
    "this call is being recorded" notice into the room."""
    if start_recording_with_retry(
        token,
        post_start=_post_start_recording,
        is_active=lambda tok: tok in _ACTIVE_CALLS,
        on_failed=alert_recording_not_started,
    ):
        _post_recording_notice(token)


# Talk shows its own recording indicator, but the people in the call are
# owed the why and the scope in plain words (GDPR transparency), so the room
# owner says it the moment recording really starts. Informing participants
# before the call is still the organiser's job; nothing here enforces it.
# A call starts a little before its recording does, and clocks drift.
_RECORDING_START_SLACK_SEC = 120.0

_RECORDING_NOTICE = (
    "\U0001f534 The audio of this call is being recorded so its minutes can "
    "be written automatically. The recording and the minutes stay internal."
)


def _post_recording_notice(token: str) -> None:
    """Post the recording notice into the Talk room. Best-effort: a
    failed notice must never undo a started recording, so it only logs."""
    status, body = _ocs_post(
        f"/ocs/v2.php/apps/spreed/api/v1/chat/{token}?format=json",
        {"message": _RECORDING_NOTICE},
    )
    if status >= 300:
        log.warning(
            "talk auto-record: recording notice for call %s returned HTTP %s: %s",
            token, status, body[:160],
        )
    else:
        log.info("talk auto-record: posted recording notice for call %s", token)


def _ingest_call(token: str, duration_sec: float | None = None) -> None:
    """Turn the finished call's recording into minutes, then give back the
    GPU held for the call."""
    try:
        _ingest_recording_of(token, duration_sec)
    finally:
        release_gpu(token)


def _ingest_recording_of(token: str, duration_sec: float | None) -> None:
    """Turn the finished call's recording into minutes. A call with no
    recording that was long enough to matter is a lost meeting and pages; a
    short call with no recording is a genuine skip."""
    title = _room_title(token) or "Video call"
    meeting_date = datetime.now(_meeting_zone()).strftime("%Y-%m-%d")
    # The room keeps every recording it ever made, so the ingest needs to know
    # when this call started: anything older belongs to an earlier one. The
    # call just ended, so its start is now minus how long it ran, with slack
    # for the gap between the call starting and the recording starting.
    not_before = None
    if duration_sec:
        not_before = time.time() - duration_sec - _RECORDING_START_SLACK_SEC
    try:
        job_id = ingest_with_wait(
            token,
            ingest=lambda tok: ingest_recording(
                tok, title, meeting_date, not_before=not_before
            ),
        )
    except Exception as exc:  # noqa: BLE001, Tier-2: a webhook must not crash on ingest hiccups
        log.warning("talk auto-notulen failed for call %s: %s", token, exc)
        return
    if job_id is not None:
        log.info("talk auto-notulen: dispatched job %s for call %s", job_id, token)
        return
    # No recording appeared even after waiting: real loss or a short-call skip.
    if should_alert_no_recording(duration_sec):
        log.warning(
            "talk auto-notulen: call %s ended with no recording "
            "(duration=%ss); paging", token, _fmt_duration(duration_sec),
        )
        alert_no_recording(token, duration_sec)
    else:
        log.info(
            "talk auto-notulen: no recording for short call %s "
            "(duration=%ss); skipped", token, _fmt_duration(duration_sec),
        )


def _fmt_duration(duration_sec: float | None) -> str:
    return "unknown" if duration_sec is None else f"{duration_sec:.0f}"


def _room_title(token: str) -> str:
    status, body = _ocs_get(f"/ocs/v2.php/apps/spreed/api/v4/room/{token}?format=json")
    if status >= 300:
        return ""
    try:
        return str(json.loads(body).get("ocs", {}).get("data", {}).get("displayName", "")).strip()
    except ValueError:
        return ""


def _ocs_post(path: str, form: dict[str, str]) -> tuple[int, str]:
    request = urllib.request.Request(
        nc_base() + path,
        data=urllib.parse.urlencode(form).encode(),
        method="POST",
        headers={
            "OCS-APIRequest": "true",
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": basic_auth(),
        },
    )
    return _send(request)


def _ocs_get(path: str) -> tuple[int, str]:
    request = urllib.request.Request(
        nc_base() + path,
        method="GET",
        headers={
            "OCS-APIRequest": "true",
            "Accept": "application/json",
            "Authorization": basic_auth(),
        },
    )
    return _send(request)


def _send(request: urllib.request.Request) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        log.warning("talk OCS call failed: %s", error)
        return -1, str(error)
