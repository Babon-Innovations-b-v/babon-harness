# apps/assistant/core/tools/agenda/

Calendar reads and writes over CalDAV (`caldav.py`, stdlib only), plus Nextcloud Talk call rooms.

- Calendars and people are settings: `AGENDA_CALENDARS`, `AGENDA_SCOPES`, optional `TEAM_CALENDAR`, signed in as `AGENDA_USER` with `AGENDA_APP_PASSWORD`.
- **The team calendar takes only whole-team events.** A meeting between some people goes on each attendee's own calendar.
- `agenda_act` removes only events it created. Writes need `ASSISTANT_AGENDA_WRITE`.
- A receipt says what the server answered, never what was intended.
