"""The six MCP tool callables, one per calendar verb, one per file.

Split out of the former ``server.py``;
``server.py`` assembles the FastMCP instance and registers these. Each tool
is a plain function (RFC5545 strings on the wire; everything else JSON) so
the offline tests call it directly without an MCP transport.

Module map:

    list_calendars.py   list_calendars(), calendars visible on the account
    list_events.py      list_events(), events in a window
    find_free_slots.py  find_free_slots(), free blocks ≥ duration_minutes
    create_event.py     create_event(), new event in a named calendar
    update_event.py     update_event(), field updates by uid, omitted = kept
    delete_event.py     delete_event(), delete by uid

FAILURE POLICY: fail-loud, tools raise ValueError / RuntimeError /
CalendarNotFound with operator-facing messages; the MCP framework
serialises them to the client.
"""
from __future__ import annotations

from .create_event import create_event
from .delete_event import delete_event
from .find_free_slots import find_free_slots
from .list_calendars import list_calendars
from .list_events import list_events
from .update_event import update_event

__all__ = [
    "create_event",
    "delete_event",
    "find_free_slots",
    "list_calendars",
    "list_events",
    "update_event",
]
