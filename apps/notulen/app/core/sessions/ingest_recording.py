"""Turn a finished Nextcloud Talk call recording into minutes.

The recording server on the media box records a call and, when it ends,
stores the recording (a `.webm` for video and audio, `.ogg` for audio only)
in the Files of the account that owns the room, under
`Talk/Recording/<token>/`, and usually also posts it as a file message in
the conversation. The owner is the assistant's Nextcloud account, which
creates every call room. This module reaches in as that account, takes the
recording, and feeds it into the same pipeline the browser recorder uses
(`process_job`, audio already in S3): upload to
`notulen/audio/<job_id>.webm`, open a `notulen_jobs` row, dispatch.

Where the recording is found: the chat file message first, then a WebDAV
listing of the `Talk/Recording/<token>/` folder, because the post to the
chat can be skipped while the file in the folder is always there.

Login: `shared/talk_account.py` (`NC_URL`, `AGENDA_USER`,
`AGENDA_APP_PASSWORD`).

FAILURE POLICY: fail-loud. A missing login, no recording found, or a
non-2xx from Nextcloud raises; a silent drop here would lose a meeting.
"""
from __future__ import annotations

import io
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from email.utils import parsedate_to_datetime

from dashkit.core.db import get_db

from apps.notulen.app.core.minutes.process_job import process_job
from apps.notulen.app.core.sessions.attendee_list import clean_attendees
from apps.notulen.app.shared.config import S3_BUCKET
from apps.notulen.app.shared.jobs_table import ensure_jobs_table
from apps.notulen.app.shared.s3 import get_s3
from apps.notulen.app.shared.talk_account import basic_auth, nc_base, talk_user

logger = logging.getLogger("notulen")

_RECORDING_SUFFIXES = (".webm", ".ogg")
# how far back to look for the same recording arriving twice
_DUPLICATE_LOOKBACK = 12
_TIMEOUT = 30


def ingest_recording(
    conversation_token: str,
    title: str,
    meeting_date: str,
    attendees: list[str] | None = None,
    agenda: str = "",
    not_before: float | None = None,
) -> str:
    """Ingest the newest recording of a Talk conversation as a notulen job.

    ``not_before`` is epoch seconds: a recording older than that belongs to an
    earlier call in the same room, not to this one.

    Returns the new job_id. Raises if no recording is found or Nextcloud is
    unreachable (fail-loud: a lost recording is the failure mode we refuse).
    """
    job_id = str(uuid.uuid4())
    # Fill the attendees from the call itself when none were given, so the
    # notulen lists the real people (nicely named from the API) and Claude can
    # map the speaker labels to them (the writer prompt already does this).
    # Cleaned either way: the count is what caps the speakers the GPU worker
    # may find, so one person listed twice buys the recording a third voice.
    attendees = clean_attendees(attendees or _room_attendees(conversation_token))
    source_path, filename, recorded_at = _newest_recording_path(conversation_token)
    _refuse_if_from_an_earlier_call(filename, recorded_at, not_before)
    _refuse_if_already_ingested(source_path, filename)
    data = _webdav_get(source_path)
    _refuse_if_same_audio_already_landed(data, filename)
    logger.info("ingest %s: fetched %s (%d bytes) for job %s",
                conversation_token, filename, len(data), job_id)
    s3_key = upload_to_s3(job_id, data)
    create_job(job_id, title, meeting_date, attendees or [], agenda, s3_key,
               source_path)
    process_job(job_id, s3_key, title, meeting_date, attendees or [], agenda)
    return job_id


class AlreadyIngested(LookupError):
    """The newest recording in this room has already been made into a notulen.

    A ``LookupError`` on purpose: to the caller this means the same thing as
    "no recording yet", because the new one is still being stored. That is what
    ``ingest_with_wait`` polls on, so the call waits for the real recording
    instead of giving up on it.
    """


def _refuse_if_from_an_earlier_call(
    filename: str, recorded_at: float, not_before: float | None
) -> None:
    """Stop when the newest recording predates the call being ingested.

    A room keeps every recording it has ever made in one folder, so "newest
    file" answers the wrong question: it is only the right file if it was made
    during this call. A rejoined room hands back an earlier recording until
    the new one has finished storing. A ``LookupError`` so the caller keeps
    waiting for the recording that does belong to this call.
    """
    if not_before is None or not recorded_at:
        return  # nothing to compare against: fall through to the other guards
    if recorded_at < not_before:
        raise LookupError(
            f"{filename} was recorded at {recorded_at:.0f}, before this call started "
            f"at {not_before:.0f}, so it belongs to an earlier call in this room"
        )


def _refuse_if_already_ingested(source_path: str, filename: str) -> None:
    """Stop before a second job is opened on a recording we already have.

    A room keeps every recording it has ever made in one folder, and Talk
    finishes storing a new one some time after the call ends. Rejoining a room
    and ingesting in that window finds the PREVIOUS recording as the newest
    file, so the same meeting would be transcribed again under a new job.
    """
    conn = get_db()
    if not conn:
        raise RuntimeError("cannot check for a duplicate ingest: database unavailable")
    try:
        ensure_jobs_table(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM notulen_jobs WHERE source_path = %s LIMIT 1",
                (source_path,),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    if row:
        raise AlreadyIngested(
            f"{filename} is already notulen job {row[0]}; the newest recording in this "
            "room is one we have transcribed, so the new one has not finished storing yet"
        )


def _refuse_if_same_audio_already_landed(data: bytes, filename: str) -> None:
    """Second guard, for recordings ingested before the path was recorded.

    ``source_path`` only protects jobs opened since it existed, and the folder
    a room records into still holds everything from before that. Recording
    bytes are not reproducible between calls, so a byte length that matches a
    job we already hold means the same file, not a coincidence.
    """
    conn = get_db()
    if not conn:
        raise RuntimeError("cannot check for a duplicate ingest: database unavailable")
    try:
        ensure_jobs_table(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, s3_audio_key FROM notulen_jobs "
                "WHERE s3_audio_key IS NOT NULL "
                "ORDER BY created_at DESC NULLS LAST LIMIT %s",
                (_DUPLICATE_LOOKBACK,),
            )
            recent = cur.fetchall() or []
    finally:
        conn.close()

    s3 = get_s3()
    for job_id, key in recent:
        try:
            size = s3.head_object(Bucket=S3_BUCKET, Key=key)["ContentLength"]
        except Exception:
            continue  # a missing object tells us nothing; keep looking
        if size == len(data):
            raise AlreadyIngested(
                f"{filename} is byte-for-byte the size of notulen job {job_id}, so this is "
                "a recording we already have; the new one has not finished storing yet"
            )


def upload_to_s3(job_id: str, data: bytes) -> str:
    """Put the recording bytes at the notulen S3 key grammar and return it.
    The key stays `.webm` (the pipeline downloads by key and decodes by
    content, so an `.ogg` recording rides the same key fine)."""
    s3_key = f"notulen/audio/{job_id}.webm"
    get_s3().upload_fileobj(io.BytesIO(data), S3_BUCKET, s3_key)
    return s3_key


def create_job(
    job_id: str, title: str, meeting_date: str, attendees: list[str],
    agenda: str, s3_key: str, source_path: str | None = None,
) -> None:
    """Open a `notulen_jobs` row (status pending) with the audio already in
    S3, created by the room owner's account, tied to the recording it came
    from, which is what keeps one recording from becoming two jobs."""
    conn = get_db()
    if not conn:
        raise RuntimeError("notulen_jobs insert failed: database unavailable")
    try:
        ensure_jobs_table(conn)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO notulen_jobs "
                "(id, status, title, meeting_date, attendees, agenda, "
                " created_by, s3_audio_key, source_path) "
                "VALUES (%s, 'pending', %s, %s, %s, %s, %s, %s, %s)",
                (job_id, title, meeting_date, attendees, agenda, talk_user(), s3_key,
                 source_path),
            )
        conn.commit()
    finally:
        conn.close()


# --- Nextcloud access ---

def _newest_recording_path(conversation_token: str) -> tuple[str, str, float]:
    """(files-relative path, filename, epoch seconds) of the newest recording
    file posted in the conversation. Reads the recent chat and picks the latest
    file message whose name is a recording. `LookupError` if none is present
    yet. The time comes back because a room holds every recording it ever made,
    so which one belongs to the call being ingested is a question about when."""
    url = (
        f"{nc_base()}/ocs/v2.php/apps/spreed/api/v1/chat/{conversation_token}"
        "?format=json&lookIntoFuture=0&limit=200"
    )
    status, body = _ocs_get(url)
    if status >= 300:
        raise RuntimeError(f"reading Talk chat failed: HTTP {status}")
    messages = json.loads(body).get("ocs", {}).get("data", []) or []
    best: tuple[int, str, str] | None = None  # (timestamp, path, name)
    for message in messages:
        for param in (message.get("messageParameters") or {}).values():
            if not isinstance(param, dict) or param.get("type") != "file":
                continue
            name = str(param.get("name", ""))
            path = str(param.get("path", ""))
            if not path or not name.lower().endswith(_RECORDING_SUFFIXES):
                continue
            timestamp = int(message.get("timestamp", 0))
            if best is None or timestamp > best[0]:
                best = (timestamp, path, name)
    if best is not None:
        return best[1], best[2], float(best[0])
    # Fallback: the recording server always stores the file in the owner's Files
    # under Talk/Recording/<token>/, but it is not ALWAYS posted as a chat file
    # message (the store-to-chat step can be skipped). The folder is the reliable source, so list it when the chat had
    # nothing.
    found = _recording_in_talk_folder(conversation_token)
    if found is not None:
        return found
    raise LookupError(
        f"no recording file found for conversation {conversation_token} yet"
    )


def _recording_in_talk_folder(conversation_token: str) -> tuple[str, str, float] | None:
    """(files-relative path, filename, epoch seconds) of the newest recording in the owner's
    `Talk/Recording/<token>/` folder over WebDAV, or None if the folder is
    absent/empty. The recording server writes here as the owner; the
    folder name is stable (English 'Talk/Recording'), unlike the chat post."""
    user = talk_user()
    folder = f"Talk/Recording/{conversation_token}/"
    url = f"{nc_base()}/remote.php/dav/files/{user}/{urllib.parse.quote(folder)}"
    request = urllib.request.Request(
        url, method="PROPFIND",
        headers={"Authorization": basic_auth(), "Depth": "1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise RuntimeError(f"listing Talk recording folder failed: HTTP {error.code}") from error
    prefix = f"/remote.php/dav/files/{user}/"
    best: tuple[float, str, str] | None = None  # (epoch seconds, path, name)
    for response_block in re.split(r"</[a-z]*:?response>", body, flags=re.IGNORECASE):
        href_match = re.search(r"<[a-z]*:?href[^>]*>(.*?)</[a-z]*:?href>", response_block, re.IGNORECASE | re.DOTALL)
        if not href_match:
            continue
        href = urllib.parse.unquote(href_match.group(1).strip())
        name = href.rstrip("/").split("/")[-1]
        if not name.lower().endswith(_RECORDING_SUFFIXES):
            continue
        modified_match = re.search(r"<[a-z]*:?getlastmodified[^>]*>(.*?)</[a-z]*:?getlastmodified>", response_block, re.IGNORECASE | re.DOTALL)
        modified = modified_match.group(1).strip() if modified_match else ""
        path = href[len(prefix):] if href.startswith(prefix) else href.lstrip("/")
        when = _http_date_to_epoch(modified)
        if best is None or when > best[0]:
            best = (when, path, name)
    if not best:
        return None
    return best[1], best[2], best[0]


def _http_date_to_epoch(http_date: str) -> float:
    """Epoch seconds for a WebDAV `getlastmodified`, 0.0 when unreadable.

    Never compare these dates as strings. RFC 1123 puts the weekday name
    first, so string order is not date order: the folder's newest recording
    would lose to an older one, the earlier-call guard would then refuse it,
    and a recorded meeting would be reported as never recorded.

    An unreadable date sorts last rather than dropping the file: a folder
    where nothing parses still returns its first recording with 0.0, which is
    the value `_refuse_if_from_an_earlier_call` reads as "unknown, let it
    through".
    """
    try:
        return parsedate_to_datetime(http_date).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _room_attendees(conversation_token: str) -> list[str]:
    """Display names of the people in the Talk conversation, from the API, so
    the notulen lists the real attendees and Claude can map the speaker labels
    to them. Excludes the room owner account and unnamed guests. Returns
    [] on any failure (a missing attendee list must not stop the notulen)."""
    url = (
        f"{nc_base()}/ocs/v2.php/apps/spreed/api/v4/room/"
        f"{conversation_token}/participants?format=json"
    )
    status, body = _ocs_get(url)
    if status >= 300:
        return []
    names: list[str] = []
    for participant in json.loads(body).get("ocs", {}).get("data", []) or []:
        if participant.get("actorId") == talk_user():
            continue  # the room owner and recording account, not an attendee
        name = str(participant.get("displayName", "")).strip()
        if name and name.lower() not in ("guest", "gast"):
            names.append(name)
    # Somebody on two devices is two participants, and Talk can spell their
    # name differently in each.
    return clean_attendees(names)


def _webdav_get(files_relative_path: str) -> bytes:
    """Download a file from the owner's Files over WebDAV."""
    user = talk_user()
    quoted = urllib.parse.quote(files_relative_path.lstrip("/"))
    url = f"{nc_base()}/remote.php/dav/files/{user}/{quoted}"
    request = urllib.request.Request(
        url, method="GET", headers={"Authorization": basic_auth()}
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"WebDAV download failed: HTTP {error.code}") from error


def _ocs_get(url: str) -> tuple[int, str]:
    request = urllib.request.Request(
        url, method="GET",
        headers={
            "OCS-APIRequest": "true",
            "Accept": "application/json",
            "Authorization": basic_auth(),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")


def main() -> int:
    """CLI: ingest a Talk recording by conversation token, from inside the
    notulen container, the manual rescue for a call the webhook missed.
    `python -m apps.notulen.app.core.sessions.ingest_recording <token> "<title>" <YYYY-MM-DD> [--attendees a,b] [--agenda text]`."""
    import argparse

    parser = argparse.ArgumentParser(description="Ingest a Talk call recording as a notulen.")
    parser.add_argument("token", help="the Talk conversation token")
    parser.add_argument("title", help="meeting title")
    parser.add_argument("meeting_date", help="YYYY-MM-DD")
    parser.add_argument("--attendees", default="", help="comma-separated names")
    parser.add_argument("--agenda", default="")
    args = parser.parse_args()

    attendees = [name.strip() for name in args.attendees.split(",") if name.strip()]
    job_id = ingest_recording(
        args.token, args.title, args.meeting_date, attendees, args.agenda
    )
    print(f"minutes job dispatched: {job_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
