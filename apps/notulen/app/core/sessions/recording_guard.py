"""Make the Talk auto-recording reliable and never silent.

Nextcloud fires `call_started` before the call is recordable: a single
`status:1` post to the OCS recording API at that instant can be answered
`400 {"error":"call"}`, and if nothing retries, a whole meeting goes
unrecorded with nobody told. This module is the guard, in three
injectable pieces:

- `is_call_not_ready` reads the OCS answer and says "the call is not
  recordable yet" (the retryable race) or a real error.
- `start_recording_with_retry` keeps asking to start until the call is
  recordable, the call ends, or a deadline passes; it pages only on a real
  failure, never on the retryable race.
- `should_alert_no_recording` decides, when a call ends with no recording,
  whether that is a short-call skip (silent) or a lost meeting (page).

Collaborators (the OCS post, the "is this call still active?" check, the
clock, the pager) are injected so the whole guard is testable without a
live Talk server. The page copy lives in `alert_recording.py`.
"""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable

logger = logging.getLogger("notulen")

# The call takes a moment to become recordable after `call_started`; the
# recording backend registers the session and (for some rooms) a second
# participant joins. 5 min of 10s retries comfortably covers both while
# staying cheap (a sleeping daemon thread). Past that on a still-active
# call, something is really wrong -> page.
_RETRY_INTERVAL_SEC = 10.0
_RETRY_MAX_WAIT_SEC = 300.0

# A call shorter than this that produced no recording is a genuine skip
# (someone joined and left, a mis-click), not a lost meeting. Above it, or
# when the duration is unknown, a missing recording is a real loss.
_MIN_MEANINGFUL_CALL_SEC = 120.0

# The recording server finalizes and uploads the .webm a little AFTER the
# call ends, so the file is not there the instant `call_ended` fires. Poll
# for it before concluding it is missing -- otherwise every good call looks
# like a lost one. Only past this wait is "no recording" real.
_INGEST_POLL_INTERVAL_SEC = 20.0
_INGEST_MAX_WAIT_SEC = 300.0


def is_call_not_ready(status: int, body: str) -> bool:
    """True when the OCS recording-start answer is the retryable "the call
    is not in progress yet" race: HTTP 400 with `data.error == "call"`.
    Any other answer (200, or a different error) is not this race."""
    if status != 400:
        return False
    try:
        data = json.loads(body).get("ocs", {}).get("data", {})
    except (ValueError, AttributeError):
        return False
    return isinstance(data, dict) and data.get("error") == "call"


def should_alert_no_recording(
    duration_sec: float | None, *, min_duration_sec: float = _MIN_MEANINGFUL_CALL_SEC
) -> bool:
    """A call ended with no recording: page or stay silent? Page when the
    call lasted at least `min_duration_sec` (a real meeting was lost), or
    when the duration is unknown (err toward paging over silent loss). Stay
    silent for a short call (a genuine skip)."""
    if duration_sec is None:
        return True
    return duration_sec >= min_duration_sec


def ingest_with_wait(
    token: str,
    *,
    ingest: Callable[[str], str],
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    interval_sec: float = _INGEST_POLL_INTERVAL_SEC,
    max_wait_sec: float = _INGEST_MAX_WAIT_SEC,
) -> str | None:
    """Ingest the call's recording, polling past the finalize/upload delay.

    Returns the notulen job_id once the recording is found and dispatched, or
    None if no recording appeared within `max_wait_sec` (only then is it truly
    missing). `ingest` raises `LookupError` while the recording is not there
    yet; any other error propagates to the caller's Tier-2 handler.
    """
    loop_start = monotonic()
    while True:
        try:
            return ingest(token)
        except LookupError:
            if monotonic() - loop_start >= max_wait_sec:
                return None
            logger.info(
                "talk auto-notulen: recording for call %s not ready yet, waiting", token
            )
            sleep(interval_sec)


def start_recording_with_retry(
    token: str,
    *,
    post_start: Callable[[str], tuple[int, str]],
    is_active: Callable[[str], bool],
    on_failed: Callable[[str, str], None],
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    interval_sec: float = _RETRY_INTERVAL_SEC,
    max_wait_sec: float = _RETRY_MAX_WAIT_SEC,
) -> bool:
    """Ask Nextcloud to start recording call `token`, retrying past the
    "call not in progress yet" race until it starts, the call ends, or the
    deadline passes. Returns True once recording started.

    Pages (`on_failed`) only on a real failure: a non-retryable error from
    the OCS API, or the deadline passing while the call is still active. If
    the call ends first, it returns quietly: the no-recording check on
    `call_ended` is the net for that case, so a short call never pages here.
    """
    loop_start = monotonic()
    while True:
        if not is_active(token):
            logger.info(
                "talk auto-record: call %s ended before recording started; "
                "leaving the no-recording check to ingest", token,
            )
            return False
        status, body = post_start(token)
        if status == 200:
            logger.info("talk auto-record: recording started for call %s", token)
            return True
        if is_call_not_ready(status, body):
            if monotonic() - loop_start >= max_wait_sec:
                reason = (
                    f"call still not recordable after {int(max_wait_sec)}s "
                    "(spreed kept answering error 'call')"
                )
                logger.warning("talk auto-record: %s for call %s", reason, token)
                on_failed(token, reason)
                return False
            sleep(interval_sec)
            continue
        reason = f"recording start returned HTTP {status}: {body[:160]}"
        logger.warning("talk auto-record: %s for call %s", reason, token)
        on_failed(token, reason)
        return False
