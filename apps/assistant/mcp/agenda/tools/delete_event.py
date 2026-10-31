"""delete_event tool, remove an event by uid from a named calendar."""
from __future__ import annotations

from ..runtime import ensure_client


def delete_event(uid: str, calendar: str) -> dict:
    """Delete the event by uid from the named calendar.

    Returns {ok: True, uid} on success. KeyError if no such event.
    """
    client = ensure_client()
    raw = client.fetch_event(calendar, uid)
    raw.delete()
    return {"ok": True, "uid": uid}
