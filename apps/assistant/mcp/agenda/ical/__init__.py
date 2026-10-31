"""Pure iCal RFC5545 domain for harness-agenda, no network, no MCP.

Split out of the former single ``events.py``. iCloud expects standards-compliant VEVENT blobs (UID, DTSTAMP,
DTSTART, DTEND, SUMMARY required; LOCATION, DESCRIPTION, RRULE optional).
datetime objects are serialised in UTC to dodge tzid/floating-time
ambiguity, iCloud renders them in the viewer's local tz on display.

Module map (one public callable per file):

    event.py       Event, the in-process shape used by the MCP tools
    build_vcal.py  build_vcal(), one Event → VCALENDAR bytes for save_event
    parse_vcal.py  parse_vcal(), VCALENDAR blob → Event (the inverse)
    parse_iso.py   parse_iso(), ISO8601 string → aware UTC datetime
    new_uid.py     new_uid(), fresh ``@harness-agenda`` UID
    find_free.py   find_free() + FreeSlot, free-slot maths over events
    utc.py         utc(), coerce a datetime to aware UTC
    iso.py         iso(), datetime → UTC ISO8601 string (inverse of parse_iso)

What this package does NOT own: CalDAV transport (../client.py), the MCP
tool surface (../tools/), credentials (../secrets.py).

Requires ``icalendar``, a dependency that does not ship in the
workspace env (declared exception in the parent package docstring); the
co-located tests importorskip it.
"""
from __future__ import annotations

from .build_vcal import build_vcal
from .event import Event
from .find_free import FreeSlot, find_free
from .iso import iso
from .new_uid import new_uid
from .parse_iso import parse_iso
from .parse_vcal import parse_vcal
from .utc import utc

__all__ = [
    "Event",
    "FreeSlot",
    "build_vcal",
    "find_free",
    "iso",
    "new_uid",
    "parse_iso",
    "parse_vcal",
    "utc",
]
