"""What happens to a set of minutes after the machine is done with it: read
the committed text, correct it, hand it to the assistant.

Owns three routes and no policy. The file is the truth (`core/publish/github`
reads and rewrites it), the one-shot claim and the handoff are
`core/board/`, and the row projection for the job list stays in
`jobs_routes.py`.

WHY THE FILE AND NOT THE ROW. `notulen_jobs.output_markdown` is the machine's
first draft and is deliberately never touched by a save, so the two can be
compared later. That makes the row the wrong thing to show in an editor the
moment anybody corrects anything, so these routes read and write the
committed file.

WHO DID IT. Both writes are attributed, so the commit and the audit row name
a person rather than the dashboard. The name comes from the single sign-on
headers (`shared/identity.py`).

FAILURE POLICY: Tier-1 at every seam. A save that did not commit answers with
an error, never a page that looks saved; the send answers with what the
assistant did or with why it could not. Both are a person waiting on a button.
"""
from __future__ import annotations

import logging

import requests
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from dashkit.core import audit as _audit
from dashkit.core.db import get_db

from apps.notulen.app.core.board.claim_send import claim_send
from apps.notulen.app.core.board.send_to_assistant import (
    AssistantUnreachable,
    send_to_assistant,
)
from apps.notulen.app.core.publish.github.read_notulen import read_notulen
from apps.notulen.app.core.publish.github.rewrite_notulen import (
    NotulenMovedOn,
    rewrite_notulen,
)
from apps.notulen.app.shared.config import target_branch, target_repo
from apps.notulen.app.shared.identity import who
from apps.notulen.app.shared.jobs_table import ensure_jobs_table
from apps.notulen.app.shared.update_job import update_job

log = logging.getLogger("notulen")
router = APIRouter()


class _Save(BaseModel):
    markdown: str
    sha: str


def _log(action: str, user: str, detail: dict) -> None:
    """One audit row in ``notulen_activity``; the helper itself fails open."""
    conn = get_db()
    if not conn:
        return
    try:
        _audit.log_activity(conn, "notulen_activity", action, user, detail=detail)
        conn.commit()
    finally:
        conn.close()


def _committed_job(job_id: str) -> tuple[str, str, str, str, list[int] | None]:
    """(path, title, meeting_date, commit_url, board_issues) for a notulen
    that reached git, or an HTTP error saying why it cannot be edited yet."""
    conn = get_db()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        ensure_jobs_table(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT output_path, title, meeting_date, output_commit_url, "
                "board_issues, status FROM notulen_jobs WHERE id = %s",
                (job_id,),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    path, title, meeting_date, commit_url, board_issues, status = row
    if not path:
        # The path is not derivable from the title and the date because of
        # the slot walk, so a row without one cannot be opened for editing.
        raise HTTPException(
            status_code=409,
            detail=(
                "The dashboard does not know where these minutes were "
                "committed, so they can only be edited in the repository."
                if status == "complete"
                else f"These minutes are not committed yet (status {status})."
            ),
        )
    return path, title, str(meeting_date), commit_url, board_issues


@router.get("/api/jobs/{job_id}/minutes")
def _read_minutes(job_id: str):
    """The committed minutes as they stand now, with the version to save over."""
    path, _title, _date, commit_url, board_issues = _committed_job(job_id)
    try:
        markdown, sha = read_notulen(path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"No file committed at {path}")
    except KeyError as exc:
        raise HTTPException(status_code=503, detail=f"No GitHub token: {exc}") from exc
    except requests.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"GitHub said no: {exc}") from exc
    return {
        "path": path,
        "markdown": markdown,
        "sha": sha,
        "commit_url": commit_url,
        "sent_to_assistant": board_issues is not None,
        "board_issues": board_issues or [],
    }


@router.put("/api/jobs/{job_id}/minutes")
def _save_minutes(job_id: str, save: _Save, request: Request):
    """Commit a corrected notulen over the file it came from.

    The row is deliberately left alone: `output_markdown` stays the machine's
    original so the correction can be seen for what it is.
    """
    path, title, meeting_date, _url, _issues = _committed_job(job_id)
    user = who(request)
    try:
        commit_url = rewrite_notulen(
            path,
            save.markdown,
            save.sha,
            f"notulen: {title} ({meeting_date}) corrected by {user} [job:{job_id}]",
        )
    except NotulenMovedOn as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=503, detail=f"No GitHub token: {exc}") from exc
    except requests.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"GitHub said no: {exc}") from exc

    update_job(job_id, output_commit_url=commit_url)
    _log("minutes_edited", user, {"job_id": job_id, "path": path})
    return {"ok": True, "commit_url": commit_url, "path": path}


@router.post("/api/jobs/{job_id}/send-to-assistant")
def _send_to_assistant(job_id: str, request: Request):
    """Hand the corrected minutes to the assistant, once.

    The claim is taken before the assistant is called, so a second press
    opens nothing. It is given back only when the request never reached the
    assistant: a call that arrived and then timed out may have opened half a
    meeting, and re-sending that would double it.
    """
    path, title, meeting_date, _url, _issues = _committed_job(job_id)
    user = who(request)
    try:
        markdown, _sha = read_notulen(path)
    except (FileNotFoundError, KeyError, requests.HTTPError) as exc:
        raise HTTPException(status_code=502, detail=f"Could not read {path}: {exc}") from exc

    if not claim_send(job_id):
        raise HTTPException(
            status_code=409,
            detail="These minutes were already sent to the assistant.",
        )

    try:
        issues = send_to_assistant(
            job_id, title, meeting_date, markdown,
            f"https://github.com/{target_repo()}/blob/{target_branch()}/{path}",
        )
    except (AssistantUnreachable, KeyError) as exc:
        # Nothing was opened, so the button goes back to being pressable.
        update_job(job_id, board_sent_at=None)
        raise HTTPException(status_code=502, detail=f"The assistant never got it: {exc}") from exc
    except requests.HTTPError as exc:
        update_job(job_id, board_sent_at=None)
        raise HTTPException(status_code=502, detail=f"The assistant refused: {exc}") from exc
    except requests.Timeout as exc:
        # It arrived. The assistant may be halfway through opening the
        # meeting, so the claim stands and a person reads Signal.
        log.warning("send-to-assistant for %s timed out after arriving: %s", job_id, exc)
        raise HTTPException(
            status_code=504,
            detail=(
                "The assistant took the meeting but did not answer in time. It "
                "is probably still working; check Signal before doing anything."
            ),
        ) from exc

    update_job(job_id, board_issues=issues)
    _log("minutes_sent_to_assistant", user, {"job_id": job_id, "issues": issues})
    return {"ok": True, "issues": issues}
