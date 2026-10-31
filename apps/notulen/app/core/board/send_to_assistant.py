"""Post corrected minutes to the assistant and report the issues it touched.

The dashboard does not read the minutes and does not choose where anything
lands; it hands the assistant the meeting and waits. The assistant's
``/webhook/notulen`` route is bearer-gated on the same shared secret every
other machine-to-assistant call uses (``OPENCLAW_WEBHOOK_SECRET``), at the
base URL ``OPENCLAW_NOTIFY_URL``.

WHY IT WAITS. The person pressing the button wants to see what happened. The
assistant takes tens of seconds (it reads the minutes, looks up which issues
they touch, then writes), so the wait is long by web standards and short by
meeting standards.

TWO FAILURES THAT ARE NOT THE SAME. A call that never reached the assistant
opened nothing, so the caller may clear its claim and let the button be
pressed again. A call that reached it and then timed out may have opened half
a meeting, so the claim stands and a person looks. `AssistantUnreachable` is
the first of those and nothing else.

FAILURE POLICY: Tier-1, raises. A send that failed must reach the person who
pressed the button.
"""
from __future__ import annotations

import os
from typing import Optional

import requests

#: Long enough for the assistant to read a meeting and write a handful of issues.
SEND_TIMEOUT_S = 240


class AssistantUnreachable(RuntimeError):
    """The request never reached the assistant, so nothing was opened."""


def send_to_assistant(
    job_id: str,
    title: str,
    meeting_date: str,
    minutes_markdown: str,
    minutes_url: str,
    *,
    session: Optional[requests.Session] = None,
) -> list[int]:
    """Hand the assistant the meeting; return the issues its work now sits on.

    That is what the assistant opened plus what it found already on the board
    and updated instead of opening again. An empty list is a real answer: a
    meeting with no action items and no decisions leaves the board alone.

    Raises:
        KeyError: `OPENCLAW_WEBHOOK_SECRET` or `OPENCLAW_NOTIFY_URL` is unset.
        AssistantUnreachable: the request never arrived; nothing was opened.
        requests.HTTPError: the assistant answered, and said no.
    """
    secret = os.environ.get("OPENCLAW_WEBHOOK_SECRET", "").strip()
    if not secret:
        raise KeyError("OPENCLAW_WEBHOOK_SECRET")
    base = os.environ.get("OPENCLAW_NOTIFY_URL", "").strip().rstrip("/")
    if not base:
        raise KeyError("OPENCLAW_NOTIFY_URL")

    http = session or requests.Session()
    try:
        response = http.post(
            f"{base}/webhook/notulen",
            headers={"Authorization": f"Bearer {secret}"},
            json={
                "job_id": job_id,
                "title": title,
                "meeting_date": meeting_date,
                "markdown": minutes_markdown,
                "minutes_url": minutes_url,
            },
            timeout=SEND_TIMEOUT_S,
        )
    except requests.ConnectionError as exc:
        raise AssistantUnreachable(f"could not reach the assistant: {exc}") from exc
    response.raise_for_status()
    answer = response.json()
    touched = (answer.get("issues") or []) + (answer.get("updated") or [])
    return [int(number) for number in touched]
