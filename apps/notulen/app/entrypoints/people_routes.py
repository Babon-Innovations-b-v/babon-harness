"""The people the dashboard offers as attendees (GET /api/people).

The recorder's attendee chips come from here: the signed-in person, read from
the single sign-on headers, followed by the ``NOTULEN_ATTENDEES`` list from
``config/harness.env``. Nobody else is known to the dashboard; anyone else is
typed into the free-text field.

FAILURE POLICY: pure reads, nothing to swallow.
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from apps.notulen.app.core.sessions.attendee_list import clean_attendees
from apps.notulen.app.shared.config import default_attendees
from apps.notulen.app.shared.identity import who

router = APIRouter()


@router.get("/api/people")
def _people(request: Request):
    """The signed-in person first, then the configured attendees, each once."""
    signed_in = who(request)
    first = [] if signed_in == "anonymous" else [signed_in]
    return {"people": clean_attendees(first + default_attendees())}
