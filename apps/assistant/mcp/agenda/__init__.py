"""agenda MCP: a CalDAV server for the owner's file cloud calendars.

Exposes six tools to a Claude session: list_calendars, list_events,
find_free_slots, create_event, update_event, delete_event. Signs in to the
CalDAV root at AGENDA_BASE_URL (normally Nextcloud's
https://cloud.<domain>/remote.php/dav) as AGENDA_USER with the app password
AGENDA_APP_PASSWORD. AGENDA_CALENDARS, when set, narrows which calendars it
shows to the ones it names (the same setting the assistant's own agenda tools
read).

Module map (one concern per file):

    secrets.py   load_credentials(): the three settings above, from the env
    ical/        pure iCal domain subpackage: Event, build_vcal/parse_vcal,
                 parse_iso, new_uid, find_free (+FreeSlot), one per file
    client.py    AgendaClient: the one caldav-aware adapter
    runtime.py   ensure_client(): process-global lazy CalDAV client cache
                 (the test seam; shared by every tools/ file)
    tools/       the six MCP tool callables, one per calendar verb per file
    serve.py     serve(): run the server on stdio or a network transport
    server.py    main(): FastMCP assembly

No re-exports BY DESIGN: importing this seam must not require caldav or mcp.
Consumers are MCP clients, never Python imports.

FAILURE POLICY: fail-loud. SecretsUnavailable, CalendarNotFound and auth
errors propagate to the MCP layer, which surfaces them as tool errors; no
silent fallback calendars.
"""
