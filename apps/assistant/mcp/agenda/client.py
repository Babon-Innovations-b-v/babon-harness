"""CalDAV client wrapper for the owner's file cloud.

Thin layer on top of `caldav.DAVClient` that:
- connects to AGENDA_BASE_URL as AGENDA_USER,
- caches the principal and calendar list for the MCP session,
- narrows the list to AGENDA_CALENDARS when that is set,
- offers calendar lookup by display name OR url path.

Quirks tolerated:
- a server may list a non-writable system calendar (reminders); we surface a
  `writable` flag based on supported_calendar_component_set.
- some servers answer 412 Precondition Failed on REPORT-by-UID queries, so an
  event is fetched by its deterministic URL instead, which works because
  save_event uses ``{uid}.ics`` as the resource name.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

import caldav
from caldav.lib.error import AuthorizationError, NotFoundError

from .secrets import CalDavCredentials




class CalendarNotFound(KeyError):
    """Lookup by name or path returned nothing."""


@dataclass
class CalendarHandle:
    name: str
    url: str
    writable: bool
    _cal: caldav.Calendar


class AgendaClient:
    """Per-process CalDAV client. Connect once, reuse the principal."""

    def __init__(self, credentials: CalDavCredentials):
        self._client = caldav.DAVClient(
            url=credentials.base_url,
            username=credentials.user,
            password=credentials.app_password,
        )
        try:
            self._principal = self._client.principal()
        except AuthorizationError as exc:
            raise RuntimeError(
                "the CalDAV server rejected AGENDA_USER / AGENDA_APP_PASSWORD. "
                "Create a new app password for that account and put it in the vault."
            ) from exc
        self._calendars_cache: list[CalendarHandle] | None = None

    def calendars(self, refresh: bool = False) -> list[CalendarHandle]:
        if self._calendars_cache is not None and not refresh:
            return self._calendars_cache
        handles: list[CalendarHandle] = []
        wanted = _wanted_locations()
        for cal in self._principal.calendars():
            handle = _handle_for(cal)
            if wanted and not any(handle.url.rstrip("/").endswith(where) for where in wanted):
                continue
            handles.append(handle)
        self._calendars_cache = handles
        return handles

    def find(self, identifier: str) -> CalendarHandle:
        """Resolve a calendar by display name or URL path. Case-insensitive."""
        ident = identifier.strip().lower()
        for handle in self.calendars():
            if handle.name.lower() == ident:
                return handle
            if handle.url.lower().rstrip("/").endswith(ident.rstrip("/")):
                return handle
        raise CalendarNotFound(
            f"no calendar matches {identifier!r}. "
            f"Available: {[h.name for h in self.calendars()]}"
        )

    def fetch_event(self, calendar_id: str, uid: str) -> caldav.Event:
        """Fetch an event we previously created.

        Uses the deterministic URL ``{calendar_url}{uid}.ics`` because
        some servers reject REPORT-by-UID with 412 Precondition Failed. This
        works for any event whose resource name follows the UID-based
        convention save_event uses. For events created outside this
        MCP (Calendar.app, third-party clients), the resource name is
        opaque and a time-range search would be required, out of
        scope for the create/update/delete path.
        """
        cal = self.find(calendar_id)._cal
        url = f"{str(cal.url).rstrip('/')}/{quote(uid, safe='')}.ics"
        try:
            return cal.event_by_url(url)
        except NotFoundError as exc:
            raise KeyError(f"event {uid!r} not in calendar {calendar_id!r}") from exc


def _handle_for(cal: caldav.Calendar) -> CalendarHandle:
    try:
        name = cal.get_display_name() or _path_tail(str(cal.url))
    except Exception:
        name = _path_tail(str(cal.url))
    components = _supported_components(cal)
    writable = "VEVENT" in components
    return CalendarHandle(
        name=name,
        url=str(cal.url),
        writable=writable,
        _cal=cal,
    )


def _wanted_locations() -> list[str]:
    """The collection names AGENDA_CALENDARS and TEAM_CALENDAR declare for
    nextcloud, or [] for no narrowing. Entries are
    `key=backend|location[|Display]`."""
    import os

    found: list[str] = []
    for entry in os.environ.get("AGENDA_CALENDARS", "").split(","):
        _key, separator, rest = entry.strip().partition("=")
        parts = rest.split("|")
        if separator and len(parts) >= 2 and parts[0].strip().lower() == "nextcloud":
            found.append(parts[1].strip().rstrip("/"))
    team = os.environ.get("TEAM_CALENDAR", "").strip().rstrip("/")
    return found + [team] if (found and team) else found


def _path_tail(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1] or url


def _supported_components(cal: caldav.Calendar) -> set[str]:
    """Return the set of VCALENDAR components this calendar accepts.

    Some servers return the property as ``{tag: ['VEVENT']}`` (a list of
    component names), different from the ElementTree shape some other
    CalDAV servers use. We tolerate both.
    """
    try:
        prop = caldav.elements.cdav.SupportedCalendarComponentSet()
        props = cal.get_properties([prop])
    except Exception:
        return {"VEVENT"}
    raw = props.get(prop.tag)
    if raw is None:
        return {"VEVENT"}
    if isinstance(raw, str):
        return {component for component in ("VEVENT", "VTODO", "VJOURNAL") if component in raw}
    if isinstance(raw, list):
        return {str(item).upper() for item in raw}
    return {child.get("name") for child in raw if hasattr(child, "get") and child.get("name")}
