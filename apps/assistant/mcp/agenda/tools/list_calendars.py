"""list_calendars tool, every calendar visible on the CalDAV account."""
from __future__ import annotations

from ..runtime import ensure_client


def list_calendars() -> list[dict]:
    """Return all calendars visible on the CalDAV account."""
    return [
        {"name": handle.name, "url": handle.url, "writable": handle.writable}
        for handle in ensure_client().calendars()
    ]
