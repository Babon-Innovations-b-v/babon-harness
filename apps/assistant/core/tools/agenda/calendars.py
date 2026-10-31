"""The calendars the assistant can reach, and the people they belong to.

Two layers:

- a **calendar** is one physical CalDAV collection the assistant can read and
  write. It carries its own server and login, so calendars can live on
  different servers. Backends: `nextcloud` (a collection on the owner's file
  cloud, signed in as AGENDA_USER with AGENDA_APP_PASSWORD) and `icloud` (an
  absolute URL, the Apple ID and app-specific password in ICLOUD_USER and
  ICLOUD_APP_PW).

- a **scope** is what a person means: `team`, `alex`, `sam`. A scope reads a
  SET of calendars (so "is Alex free" unions a work and a private calendar)
  and writes to ONE (so "put it on Alex's agenda" lands in one place). The
  LLM tools speak scopes; the calendars underneath are config.

Config, all from the environment:
- `TEAM_CALENDAR` (optional) names the shared team calendar, a collection
  under the assistant's own calendar home or a server path. When it is set,
  the `team` scope exists and takes only whole-team events; when it is unset
  there is no team calendar and that rule has nothing to guard.
- `AGENDA_CALENDARS` (comma-separated) declares further calendars:
  `key=backend|location[|Display]`. location is a collection name or server
  path for nextcloud, an absolute URL for icloud. A nextcloud calendar signs
  in as the assistant unless `AGENDA_CAL_<KEY>_USER` and `AGENDA_CAL_<KEY>_PW`
  (that person's own app password) are set.
- `AGENDA_SCOPES` (comma-separated) declares people:
  `name=readkey1+readkey2|writekey[|Display]`. A calendar key with no scope is
  also usable as a scope addressing just itself.

FAILURE POLICY: pure env parse. A malformed entry is skipped with a log line,
never taking the rest down; an unknown key resolves to None so the caller can
name the known keys back to the LLM.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from apps.assistant.core.tools.agenda import caldav

log = logging.getLogger("openclaw.agenda.calendars")

_CAL_ENV = "AGENDA_CALENDARS"
_SCOPE_ENV = "AGENDA_SCOPES"
_HOME_ENV = "AGENDA_CALENDAR_HOME"
_ICLOUD_USER_ENV = "ICLOUD_USER"
_ICLOUD_PW_ENV = "ICLOUD_APP_PW"
_TEAM_ENV = "TEAM_CALENDAR"

TEAM_KEY = "team"

# Who the assistant is talking to on this turn, or None on a loop with no person at all
# (patrol, the morning line). Module state, the same shape as the per-turn
# language gate in `message_teammate`: the read-only tool registry dispatches
# `execute(name, tool_input)` with no actor, so a read tool has no other way to
# learn whose calendar "my agenda" means.
_speaker: str | None = None


@dataclass(frozen=True)
class Calendar:
    """One physical CalDAV collection with its own server + login."""

    key: str
    display: str
    url: str            # absolute, trailing-slashed
    _user: str
    _password: str

    def request(self, method: str, subpath: str = "", body: bytes = b"", headers: dict | None = None) -> tuple[int, str]:
        return caldav.dav_request(
            method, self.url + subpath, (self._user, self._password), body, headers
        )

    def request_href(self, method: str, href: str, body: bytes = b"", headers: dict | None = None) -> tuple[int, str]:
        """Like `request`, but `href` may be a server-absolute path (as a
        multistatus response returns) or relative to the collection; urljoin
        resolves both against this calendar's URL."""
        from urllib.parse import urljoin

        return caldav.dav_request(
            method, urljoin(self.url, href), (self._user, self._password), body, headers
        )


@dataclass(frozen=True)
class Scope:
    """What a person means: a set of calendars to read, one to write."""

    name: str
    display: str
    read: list[Calendar]
    write: Calendar | None = None


def _home() -> str:
    default = f"{caldav.DAV_PATH}/calendars/{caldav.agenda_user()}/"
    home = os.environ.get(_HOME_ENV, "").strip() or default
    return home if home.endswith("/") else home + "/"


def _slash(url: str) -> str:
    return url if url.endswith("/") else url + "/"


def _own_creds(key: str) -> tuple[str, str]:
    """A teammate's OWN login for their calendar, from per-key env
    `AGENDA_CAL_<KEY>_USER` / `_PW` (their app password), or ('', '') if unset.
    Lets a calendar authenticate as the TEAMMATE, not the assistant/the owner default,
    on EITHER backend, an unshared Nextcloud calendar, or a SECOND Apple/iCloud
    account (the global `ICLOUD_USER` slot holds only one). Key is upper-cased
    with '-' -> '_'."""
    env_key = key.upper().replace("-", "_")
    user = os.environ.get(f"AGENDA_CAL_{env_key}_USER", "").strip()
    password = os.environ.get(f"AGENDA_CAL_{env_key}_PW", "").strip()
    return (user, password) if user and password else ("", "")


def _build_calendar(key: str, backend: str, location: str, display: str) -> Calendar | None:
    backend = backend.strip().lower()
    display = display.strip() or key.capitalize()
    own_user, own_pw = _own_creds(key)
    if backend == "nextcloud":
        base = location if location.startswith("/") else _home() + location
        url = caldav.BASE_URL + _slash(base)
        # A nextcloud calendar normally authenticates AS the assistant account
        # (assistant shares the collection to itself); the teammate's OWN login via
        # `_own_creds` overrides that so no server-side share is needed. Unset =
        # The assistant-account default, so every existing calendar is unchanged.
        if own_user:
            return Calendar(key, display, url, own_user, own_pw)
        token = os.environ.get(caldav._TOKEN_ENV, "").strip()
        return Calendar(key, display, url, caldav.agenda_user(), token)
    if backend == "icloud":
        # Per-key creds first, so a SECOND Apple account (e.g. A teammate's) can be
        # reached; else the global ICLOUD_USER/ICLOUD_APP_PW (the owner's).
        if own_user:
            return Calendar(key, display, _slash(location), own_user, own_pw)
        user = os.environ.get(_ICLOUD_USER_ENV, "").strip()
        password = os.environ.get(_ICLOUD_PW_ENV, "").strip()
        return Calendar(key, display, _slash(location), user, password)
    log.warning("AGENDA_CALENDARS %r has unknown backend %r; skipped", key, backend)
    return None


def calendars() -> dict[str, Calendar]:
    """key -> Calendar, read fresh from the env. `team` is present only when
    TEAM_CALENDAR names one."""
    result: dict[str, Calendar] = {}
    team = os.environ.get(_TEAM_ENV, "").strip()
    if team:
        built = _build_calendar(TEAM_KEY, "nextcloud", team, "team calendar")
        if built is not None:
            result[TEAM_KEY] = built
    for entry in os.environ.get(_CAL_ENV, "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        key, separator, rest = entry.partition("=")
        parts = rest.split("|")
        key = key.strip().lower()
        if not separator or not key or len(parts) < 2 or not parts[0].strip() or not parts[1].strip():
            log.warning("AGENDA_CALENDARS entry %r malformed; skipped", entry)
            continue
        built = _build_calendar(key, parts[0], parts[1].strip(), parts[2] if len(parts) > 2 else "")
        if built is not None:
            result[key] = built
    return result


def scopes() -> dict[str, Scope]:
    """name -> Scope. Every calendar is a self-scope (read+write itself); an
    `AGENDA_SCOPES` entry adds or overrides a person spanning several."""
    cals = calendars()
    result: dict[str, Scope] = {
        key: Scope(key, cal.display, [cal], cal) for key, cal in cals.items()
    }
    for entry in os.environ.get(_SCOPE_ENV, "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        name, separator, rest = entry.partition("=")
        parts = rest.split("|")
        name = name.strip().lower()
        read_keys = [k.strip().lower() for k in parts[0].split("+") if k.strip()] if parts else []
        read = [cals[k] for k in read_keys if k in cals]
        if not separator or not name or not read:
            log.warning("AGENDA_SCOPES entry %r malformed or names no known calendar; skipped", entry)
            continue
        write_key = parts[1].strip().lower() if len(parts) > 1 and parts[1].strip() else read_keys[0]
        write = cals.get(write_key)
        display = parts[2].strip() if len(parts) > 2 and parts[2].strip() else name.capitalize()
        result[name] = Scope(name, display, read, write)
    return result


def known_scopes() -> list[str]:
    return list(scopes().keys())


def set_speaker(name: str | None) -> None:
    """Remember who the assistant is talking to for the rest of this turn; None, an
    empty name, or simply never calling it means nobody, and the reads fall
    back to the team calendar. A loop calls this once per turn, where it clears
    the other per-turn gates."""
    global _speaker
    _speaker = (name or "").strip() or None


def default_scope_keys() -> list[str]:
    """The scopes a read defaults to when the caller named none: the speaker's
    own scope AND the team calendar, in that order.

    Their own scope is what "what does my week look like" means, and a schema
    default of `team` alone would answer it from the team calendar, because
    nothing tells the tool who is asking. The team calendar stays in the
    default because it is where the assistant's own bookings land and where "what is on
    the agenda this week" most often points, so the default is the union rather
    than a choice between the two.

    Falls back to the team alone when there is no speaker, or when the speaker
    resolves to no scope of their own, so every beat and the patrol loop see
    exactly what they saw before."""
    known = scopes()
    team = [TEAM_KEY] if TEAM_KEY in known else []
    own = (_speaker or "").strip().lower()
    if own and own != TEAM_KEY and own in known:
        return [own, *team]
    return team or list(known)


def read_calendars(who: object) -> tuple[list[Calendar], list[str]]:
    """(calendars, unknown) to READ for `who`: None/''/'all' = every calendar;
    a scope name = its read set; a list = the union."""
    scope_map = scopes()
    cal_map = calendars()
    if who is None or (isinstance(who, str) and who.strip().lower() in ("", "all")):
        return list(cal_map.values()), []
    keys = [who] if isinstance(who, str) else list(who)
    found: list[Calendar] = []
    unknown: list[str] = []
    seen: set[str] = set()
    for key in keys:
        scope = scope_map.get(str(key).strip().lower())
        if scope is None:
            unknown.append(str(key))
            continue
        for cal in scope.read:
            if cal.url not in seen:
                seen.add(cal.url)
                found.append(cal)
    return found, unknown


def write_calendar(who: object) -> Calendar | None:
    """The ONE calendar to WRITE for scope `who`, or None if unknown."""
    scope = scopes().get(str(who or TEAM_KEY).strip().lower())
    return scope.write if scope else None


def resolve_people(who: object) -> tuple[list[Scope], list[str]]:
    """(scopes, unknown) for availability: None/''/'all' = every scope; a name
    = that person; a list = several."""
    scope_map = scopes()
    if who is None or (isinstance(who, str) and who.strip().lower() in ("", "all")):
        return list(scope_map.values()), []
    keys = [who] if isinstance(who, str) else list(who)
    found: list[Scope] = []
    unknown: list[str] = []
    for key in keys:
        scope = scope_map.get(str(key).strip().lower())
        (found.append(scope) if scope else unknown.append(str(key)))
    return found, unknown
